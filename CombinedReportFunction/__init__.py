import azure.functions as func
import logging
import pandas as pd
from sqlalchemy import create_engine
from openpyxl import Workbook
from openpyxl.utils.dataframe import dataframe_to_rows
import tempfile
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from openpyxl.styles import Font
from datetime import datetime
import os

# --------------------
POSTGRES_URL = os.getenv("POSTGRES_URL")
SLACK_TOKEN = os.getenv("SLACK_TOKEN")
SLACK_CHANNEL = os.getenv("SLACK_CHANNEL")

engine = create_engine(POSTGRES_URL)
slack_client = WebClient(token=SLACK_TOKEN)

# Import queries from separate module
from .queries import TABLES


def build_excel_file():
    wb = Workbook()
    wb.remove(wb.active) 

    for sheet_name, queries in TABLES.items():
        ws = wb.create_sheet(title=sheet_name)

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")
        ws.append([f"Report generated on: {timestamp}"])
        ws.cell(row=1, column=1).font = Font(bold=True, color="000000")
        ws.append([])

        
        for query_title, sql in queries.items():

            # Query title (bold)
            ws.append([f"•  {query_title}"])
            ws.cell(row=ws.max_row, column=1).font = Font(bold=True, color="000000")

            # Execute SQL safely
            try:
                df = pd.read_sql(sql, engine)
            except Exception as e:
                df = pd.DataFrame([{"ERROR": str(e)}])

            # If no data → simple message
            if df.empty:
                ws.append(["No records found"])
                ws.cell(row=ws.max_row, column=1).font = Font(color="000000")

            else:
                # Write dataframe rows
                for row in dataframe_to_rows(df, index=False, header=True):
                    ws.append(row)

            # Blank line after each query
            ws.append([])

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
    wb.save(tmp.name)
    return tmp.name


def upload_to_slack(filepath):
    try:
        slack_client.files_upload_v2(
            channel=SLACK_CHANNEL,
            file=filepath,
            filename="CombinedReport.xlsx",
            title="Combined Report"
        )
    except SlackApiError as e:
        logging.error(f"Slack Upload Failed: {e}")


async def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("Combined Report Function Triggered.")

    try:
        excel_path = build_excel_file()
        upload_to_slack(excel_path)
        os.remove(excel_path)

        return func.HttpResponse("Combined Excel Report sent to Slack!", status_code=200)

    except Exception as e:
        logging.error(str(e))
        return func.HttpResponse(f"Error: {str(e)}", status_code=500)
