FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr tesseract-ocr-deu tesseract-ocr-est tesseract-ocr-por tesseract-ocr-tur \
    tesseract-ocr-msa tesseract-ocr-fra tesseract-ocr-spa tesseract-ocr-nld tesseract-ocr-dan \
    poppler-utils && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt pytesseract pillow pypdfium2 google-genai
COPY . .
# usage: docker run -v <pdf-folder>:/app/documents -v <out-folder>:/app/output -e GEMINI_API_KEY=... image
CMD ["python", "run.py"]
