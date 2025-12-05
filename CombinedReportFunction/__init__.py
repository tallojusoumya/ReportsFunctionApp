import azure.functions as func
import logging
import threading
import json
import os

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from .combinedreport import generate_excel_report  # ✔ correct import


SLACK_TOKEN = os.getenv("SLACK_TOKEN")   # ✔ correct
SLACK_CHANNEL = os.getenv("SLACK_CHANNEL")  # ✔ correct

slack_client = WebClient(token=SLACK_TOKEN)  # ✔ correct SDK usage


def background_job():
    try:
        file_path = generate_excel_report()   # ✔ correct calling your Excel generator

        slack_client.files_upload_v2(         # ✔ correct Slack upload
            channel=SLACK_CHANNEL,
            file=file_path,
            filename="EOD_Report.xlsx",
            title="RMS + DMS Combined EOD Report"
        )

        os.remove(file_path)   # ✔ clean temp file

        logging.info("EOD report generated and uploaded to Slack")

    except Exception as e:
        logging.error(f"Background job error: {str(e)}")


async def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("Slash command received")

    thread = threading.Thread(target=background_job)  # ✔ async thread for Slack
    thread.start()

    response = {
        "response_type": "ephemeral",
        "text": "Your EOD report is being generated. It will be sent shortly!"  # ✔ Slack requirement
    }

    return func.HttpResponse(
        json.dumps(response),
        mimetype="application/json",
        status_code=200
    )
