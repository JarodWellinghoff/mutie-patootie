FROM python:3.13.9-slim

# Force unbuffered output for proper logging in containers
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .

# Run with -u flag for unbuffered output
CMD ["python", "-u", "bot.py"]