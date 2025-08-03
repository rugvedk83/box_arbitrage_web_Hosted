# ✅ USE Playwright's official Docker image (Python + Browsers pre-installed)
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

# Set working directory inside container
WORKDIR /app

# Copy your requirements.txt file and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy your application code
COPY . .

# Expose the port Render will route traffic to
EXPOSE 10000

# Start the Flask app using gunicorn and the Render-provided PORT env variable
CMD ["gunicorn", "-b", "0.0.0.0:${PORT}", "app:app"]
