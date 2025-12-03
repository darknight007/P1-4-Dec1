# Base Image: Slim is smaller and faster
FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first (better Docker caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create a non-root user for security
RUN adduser --disabled-password --gecos "" scroogeuser && \
    chown -R scroogeuser:scroogeuser /app

USER scroogeuser

# Expose port (Documentation only, ECS handles the real mapping)
EXPOSE 8501
# Changed from 80 to 8000 cause 80 was failing due to permission issues
# Now Streamlit's default port 8501

# Run Streamlit
CMD ["streamlit", "run", "app.py", "--server.port", "8501", "--server.address", "0.0.0.0"]
