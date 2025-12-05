import pandas as pd
from sqlalchemy import create_engine
from .queries import TABLES
import os

# Read values from Azure Function App → Configuration
POSTGRES_URL_RMS = os.getenv("POSTGRES_URL_RMS")
POSTGRES_URL_DMS = os.getenv("POSTGRES_URL_DMS")

# Create engines for both databases
engine_RMS = create_engine(POSTGRES_URL_RMS)
engine_DMS = create_engine(POSTGRES_URL_DMS)


def run_sql(db_name, query):
    """Runs SQL against RMS or DMS DB."""
    if db_name.upper() == "RMS":
        return pd.read_sql(query, engine_RMS)
    elif db_name.upper() == "DMS":
        return pd.read_sql(query, engine_DMS)
    else:
        raise ValueError("Unknown DB name. Use RMS or DMS.")


def generate_excel_report():
    """Creates a single Excel file containing RMS + DMS sheets."""
    
    file_path = "/tmp/EOD_Report.xlsx"
    writer = pd.ExcelWriter(file_path, engine="openpyxl")

    # Loop through both DBs
    for db_name in ["RMS", "DMS"]:
        for sheet_name, query in TABLES.items():

            full_sheet_name = f"{db_name}_{sheet_name}"[:31]  # Excel sheet name limit

            try:
                df = run_sql(db_name, query)
                df.to_excel(writer, sheet_name=full_sheet_name, index=False)

            except Exception as e:
                # Write error in sheet instead of failing
                error_df = pd.DataFrame([{"ERROR": str(e)}])
                error_df.to_excel(writer, sheet_name=full_sheet_name, index=False)

    writer.close()
    return file_path
