FROM python:2

WORKDIR /usr/src/app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY import-mailbox-to-gmail.py .

ENTRYPOINT [ "python", "import-mailbox-to-gmail.py" ]
CMD [ "-h" ]
