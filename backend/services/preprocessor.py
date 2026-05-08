import re
import io
import logging
import random

logger = logging.getLogger(__name__)


class PreprocessorService:
    MIN_SEGMENT_LENGTH = 150
    TARGET_SEGMENT_LENGTH = 800
    MAX_SEGMENT_LENGTH = 1200

    @staticmethod
    def extract_smart_classification_preview(text: str) -> str:
        markers = []
        if re.search(r'(?i)\bарендодатель\b|\bарендатор\b', text):
            markers.append("аренда")
        if re.search(r'(?i)\bзаказчик\b|\bисполнитель\b|\bподрядчик\b', text):
            markers.append("услуги/подряд")
        if re.search(r'(?i)\bпоставщик\b|\bпокупатель\b', text):
            markers.append("поставка")
        if re.search(r'(?i)\bработник\b|\bработодатель\b', text):
            markers.append("трудовой")
        if re.search(r'(?i)\bлицензиар\b|\bлицензиат\b', text):
            markers.append("лицензионный")
        if re.search(r'(?i)\bпринципал\b|\bагент\b', text):
            markers.append("агентский")
        if re.search(r'(?i)\bnda\b|\bконфиденциальност\w*\b|\bкоммерческ\w*\s+тайн\w*\b', text):
            markers.append("нда")

        start_text = text[:400]
        
        mid_text = ""
        if len(text) > 800:
            possible_start = min(400, len(text) - 200)
            possible_end = max(possible_start, len(text) - 200)
            if possible_end > possible_start:
                rand_idx = random.randint(possible_start, possible_end)
                mid_text = text[rand_idx:rand_idx+200]
            else:
                mid_text = text[possible_start:possible_start+200]
        
        liability_text = ""
        liability_match = re.search(r'(?i)(.{0,50}(?:ответственность\s+сторон|неустойка|штраф).{0,150})', text)
        if liability_match:
            liability_text = liability_match.group(1)
        
        markers_str = ", ".join(markers) if markers else "не найдены"
        
        preview = f"[МАРКЕРЫ]: {markers_str}\n"
        preview += f"[НАЧАЛО]: {start_text}\n"
        if mid_text:
            preview += f"[СЕРЕДИНА]: {mid_text}\n"
        if liability_text:
            preview += f"[ОТВЕТСТВЕННОСТЬ]: {liability_text}\n"
            
        return preview[:1500]

    def process(self, content: bytes, filename: str) -> list[str]:
        if filename.lower().endswith(".pdf"):
            text = self._extract_pdf(content)
        else:
            text = self._extract_docx(content)
        text = self._clean_text(text)
        return self._segment(text)

    def _extract_pdf(self, content: bytes) -> str:
        try:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                return "\n".join(
                    p.extract_text(x_tolerance=1, keep_blank_chars=True) or "" 
                    for p in pdf.pages
                )
        except ImportError:
            raise RuntimeError("pdfplumber не установлен")

    def _extract_docx(self, content: bytes) -> str:
        try:
            from docx import Document
            doc = Document(io.BytesIO(content))
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except ImportError:
            raise RuntimeError("python-docx не установлен")

    def _clean_text(self, text: str) -> str:
        text = text.replace("\xa0", " ")
        text = text.replace("\u200b", "")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"^\s*\d+\s*$", "", text, flags=re.MULTILINE)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"-\n(\w)", r"\1", text)
        return text.strip()

    CLAUSE_PATTERN = re.compile(
        r"(?:^|\n)\s*"
        r"(?:"
        r"\d+(?:\.\d+)*\.\s*"
        r"|"
        r"\d+\)\s*"
        r"|"
        r"[а-яёA-Za-z]\)\s*"
        r")"
    )

    def _segment(self, text: str) -> list[str]:
        matches = list(self.CLAUSE_PATTERN.finditer(text))
        
        sample_text = text[:200].replace('\n', '\\n')
        found_patterns = self.CLAUSE_PATTERN.findall(text[:500])
        path_chosen = "clause" if len(matches) >= 2 else "paragraph"
        logger.info(
            f"DIAG: Текст (первые 200 симв): {sample_text} | "
            f"Findall(первые 500 симв): {found_patterns} | "
            f"Найдено пунктов вообще: {len(matches)} | "
            f"Выбран путь: {path_chosen}"
        )
        
        logger.debug("CLAUSE_PATTERN: найдено пунктов — %d", len(matches))

        if len(matches) >= 2:
            return self._segment_by_clauses(text, matches)

        logger.debug("Пунктов недостаточно, используется разбивка по абзацам")
        return self._segment_by_paragraphs(text)

    _CLAUSE_HEADER_MAX_LEN = 40

    @staticmethod
    def _is_section_header(clause: str) -> bool:
        return len(clause) < 40 and not clause.rstrip().endswith(".")

    def _segment_by_clauses(self, text: str, matches: list) -> list[str]:
        boundaries = [m.start() for m in matches] + [len(text)]
        raw_clauses = [
            text[boundaries[i]:boundaries[i + 1]].strip()
            for i in range(len(boundaries) - 1)
        ]
        raw_clauses = [c for c in raw_clauses if c]

        segments: list[str] = []
        buffer = ""

        for clause in raw_clauses:
            if len(clause) > self.MAX_SEGMENT_LENGTH:
                if buffer:
                    segments.append(buffer)
                    buffer = ""
                segments.extend(self._split_by_sentences(clause))
                continue

            if self._is_section_header(clause):
                buffer = (buffer + " " + clause).strip() if buffer else clause
                continue

            if buffer:
                clause = (buffer + " " + clause).strip()
                buffer = ""
            segments.append(clause)

        if buffer:
            segments.append(buffer)

        logger.info("Clause-сегментация: %d пунктов → %d сегментов", len(raw_clauses), len(segments))
        return segments

    def _segment_by_paragraphs(self, text: str) -> list[str]:
        paragraphs = [p.strip() for p in re.split(r"\n\n+", text) if p.strip()]
        segments = []
        buffer = ""
        
        for para in paragraphs:
            if len(para) > self.MAX_SEGMENT_LENGTH:
                if buffer:
                    segments.append(buffer)
                    buffer = ""
                segments.extend(self._split_by_sentences(para))
                continue
            
            if len(buffer) + len(para) < self.TARGET_SEGMENT_LENGTH:
                buffer = (buffer + " " + para).strip() if buffer else para
            else:
                if buffer:
                    segments.append(buffer)
                buffer = para
                
        if buffer:
            segments.append(buffer)
            
        return segments

    def _split_by_sentences(self, text: str) -> list[str]:
        endings = re.compile(r"(?<=[.!?])\s+(?=[А-ЯA-Z\(«\"])")
        sentences = endings.split(text)
        segments, buffer = [], ""
        for sent in sentences:
            sent = sent.strip()
            if not sent:
                continue
            if len(buffer) + len(sent) < self.TARGET_SEGMENT_LENGTH:
                buffer = (buffer + " " + sent).strip() if buffer else sent
            else:
                if buffer:
                    segments.append(buffer)
                buffer = sent
        if buffer:
            segments.append(buffer)
            
        final_segments = []
        for seg in segments:
            if len(seg) > self.MAX_SEGMENT_LENGTH:
                remaining = seg
                while remaining:
                    if len(remaining) <= self.MAX_SEGMENT_LENGTH:
                        final_segments.append(remaining)
                        break
                    
                    cutoff = remaining[:self.MAX_SEGMENT_LENGTH].rfind(". ")
                    if cutoff > self.MIN_SEGMENT_LENGTH:
                        final_segments.append(remaining[:cutoff + 1].strip())
                        remaining = remaining[cutoff + 1:].strip()
                    else:
                        cutoff = remaining[:self.MAX_SEGMENT_LENGTH].rfind(" ")
                        if cutoff > 0:
                            final_segments.append(remaining[:cutoff].strip())
                            remaining = remaining[cutoff:].strip()
                        else:
                            final_segments.append(remaining[:self.MAX_SEGMENT_LENGTH])
                            remaining = remaining[self.MAX_SEGMENT_LENGTH:]
            else:
                final_segments.append(seg)
                
        return final_segments or [text[:self.MAX_SEGMENT_LENGTH]]
