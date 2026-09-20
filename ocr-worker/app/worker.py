import os
import time
import requests
from paddleocr import PaddleOCR

ARCHIVE_API=os.getenv(
    "ARCHIVE_API",
    "http://archive:8080"
)

ocr=PaddleOCR(
    lang="en",
    use_doc_orientation_classify=True,
    use_doc_unwarping=True,
    use_textline_orientation=True
)


def process_file(path):

    result=ocr.predict(path)

    texts=[]

    for r in result:
        if hasattr(r,"json"):
            data=r.json()
            texts.extend(
                data.get("rec_texts",[])
            )

    return "\n".join(texts)



def main():

    print("OCR Worker Started")

    while True:

        # فعلاً فقط آماده است
        # مرحله اتصال API بعد از تست OCR

        time.sleep(30)


if __name__=="__main__":
    main()
