import os
import pandas as pd
from io import BytesIO
import requests

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")

def upload_to_slack_external(df: pd.DataFrame, filename: str, channel_id: str) -> dict:
    """
    Uploads a pandas DataFrame as an Excel file to a Slack channel.
    """
    buffer = BytesIO()
    df.to_excel(buffer, index=False)
    buffer.seek(0)

    response = requests.post(
        "https://slack.com/api/files.upload",
        headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
        files={"file": (filename, buffer, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"channels": channel_id, "filename": filename}
    )

    return response.json()
