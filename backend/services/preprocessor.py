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

    def _segment(self, text: str) -> list[str]:
        paragraphs = [p.strip() for p in re.split(r"\n\n+", text) if p.strip()]
        segments = []
        buffer = ""
        for para in paragraphs:
            if len(para) < 60 and not para.endswith("."):
                continue
            if len(para) > self.MAX_SEGMENT_LENGTH:
                if buffer and len(buffer) >= self.MIN_SEGMENT_LENGTH:
                    segments.append(buffer)
                    buffer = ""
                segments.extend(self._split_by_sentences(para))
                continue
            if len(buffer) + len(para) < self.TARGET_SEGMENT_LENGTH:
                buffer = (buffer + " " + para).strip() if buffer else para
            else:
                if len(buffer) >= self.MIN_SEGMENT_LENGTH:
                    segments.append(buffer)
                buffer = para
        if buffer and len(buffer) >= self.MIN_SEGMENT_LENGTH:
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
                if len(buffer) >= self.MIN_SEGMENT_LENGTH:
                    segments.append(buffer)
                buffer = sent
        if buffer and len(buffer) >= self.MIN_SEGMENT_LENGTH:
            segments.append(buffer)
        return segments or [text[:self.MAX_SEGMENT_LENGTH]]
