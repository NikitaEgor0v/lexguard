import re
import io
import logging

logger = logging.getLogger(__name__)


class PreprocessorService:
    MIN_SEGMENT_LENGTH = 80
    TARGET_SEGMENT_LENGTH = 400
    MAX_SEGMENT_LENGTH = 600

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
                return "\n".join(p.extract_text() or "" for p in pdf.pages)
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
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"^\s*\d+\s*$", "", text, flags=re.MULTILINE)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"-\n(\w)", r"\1", text)
        return text.strip()

    # Распознаёт начало пункта в позиции начала строки (с возможным ведущим пробелом)
    # либо после переноса строки \n или просто пробела.
    # Это решает проблему потери переносов строк при парсинге PDF/DOCX.
    # Поддерживает форматы:
    #   1.  2.  10.          — одноуровневый номер с точкой
    #   1.1.  5.3.  10.2.1.  — многоуровневый номер с точкой
    #   1)  5)  10)          — номер со скобкой
    #   а)  б)  в)  ...      — кириллическая буква со скобкой (подпункты)
    CLAUSE_PATTERN = re.compile(
        r"(?:^|\s)"                          # начало текста или любой пробельный символ (вкл. \n)
        r"(?:"
        r"\d+(?:\.\d+)*\.[ \t]+"             # 5.  или 5.1.  или 5.1.1. + пробел
        r"|"
        r"\d+\)[ \t]+"                        # 5) + пробел
        r"|"
        r"[а-яёa-z]\)[ \t]+"                 # а) б) в) + пробел
        r")"
    )

    def _segment(self, text: str) -> list[str]:
        # --- Попытка разбивки по пунктам договора ---
        matches = list(self.CLAUSE_PATTERN.finditer(text))
        
        # --- ДИАГНОСТИКА (Шаг 1) ---
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

        # --- Fallback: разбивка по абзацам (прежняя логика) ---
        logger.debug("Пунктов недостаточно, используется разбивка по абзацам")
        return self._segment_by_paragraphs(text)

    # Порог для определения заголовка раздела (короткий пункт без самостоятельного смысла).
    _CLAUSE_HEADER_MAX_LEN = 40

    @staticmethod
    def _is_section_header(clause: str) -> bool:
        """Заголовок раздела: короткий текст без точки в конце (напр. '6. ФОРС-МАЖОР')."""
        return len(clause) < 40 and not clause.rstrip().endswith(".")

    def _segment_by_clauses(self, text: str, matches: list) -> list[str]:
        """Разбивает текст по найденным пунктам.

        Логика объединения:
        - Пункт < 40 символов И без точки в конце (заголовок раздела) → склеить со следующим.
        - Пункт ≥ 40 символов → всегда отдельный сегмент (даже если короче MIN_SEGMENT_LENGTH).
        - Пункт > MAX_SEGMENT_LENGTH → дробить по предложениям.
        """
        boundaries = [m.start() for m in matches] + [len(text)]
        raw_clauses = [
            text[boundaries[i]:boundaries[i + 1]].strip()
            for i in range(len(boundaries) - 1)
        ]
        raw_clauses = [c for c in raw_clauses if c]

        segments: list[str] = []
        buffer = ""

        for clause in raw_clauses:
            # --- Длинный пункт: дробить по предложениям ---
            if len(clause) > self.MAX_SEGMENT_LENGTH:
                if buffer:
                    segments.append(buffer)
                    buffer = ""
                segments.extend(self._split_by_sentences(clause))
                continue

            # --- Заголовок раздела (короткий, без точки): склеить со следующим ---
            if self._is_section_header(clause):
                buffer = (buffer + " " + clause).strip() if buffer else clause
                continue

            # --- Обычный пункт ≥ 40 символов: всегда отдельный сегмент ---
            if buffer:
                # Если в буфере был заголовок — приклеиваем к текущему пункту
                clause = (buffer + " " + clause).strip()
                buffer = ""
            segments.append(clause)

        # Остаток буфера (заголовок без последующего пункта)
        if buffer:
            segments.append(buffer)

        logger.info("Clause-сегментация: %d пунктов → %d сегментов", len(raw_clauses), len(segments))
        return segments

    def _segment_by_paragraphs(self, text: str) -> list[str]:
        """Улучшенная логика: разбивка по абзацам без потери данных."""
        paragraphs = [p.strip() for p in re.split(r"\n\n+", text) if p.strip()]
        segments = []
        buffer = ""
        
        for para in paragraphs:
            # Длинный параграф: дробим по предложениям
            if len(para) > self.MAX_SEGMENT_LENGTH:
                if buffer:
                    segments.append(buffer)
                    buffer = ""
                segments.extend(self._split_by_sentences(para))
                continue
            
            # Аккумулируем абзацы до достижения TARGET_SEGMENT_LENGTH
            if len(buffer) + len(para) < self.TARGET_SEGMENT_LENGTH:
                buffer = (buffer + " " + para).strip() if buffer else para
            else:
                if buffer:
                    segments.append(buffer)
                buffer = para
                
        # Если что-то осталось в буфере (любой длины!) — сохраняем
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
        return segments or [text[:self.MAX_SEGMENT_LENGTH]]
