from flask import Flask, render_template, request, send_file

import pandas as pd
import os

app = Flask(__name__)

# ======================================
# FOLDERS
# ======================================

UPLOAD_FOLDER = "uploads"
OUTPUT_FOLDER = "output"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# ======================================
# GLOBAL MASTER DATAFRAME
# ======================================

master_df = pd.DataFrame()

# ======================================
# HOME PAGE
# ======================================

@app.route("/")
def home():

    return render_template("index.html")

# ======================================
# PROCESS FILES
# ======================================

@app.route("/process", methods=["POST"])
def process():

    global master_df

    try:

        # ===================================
        # GET FILES
        # ===================================

        sales_file = request.files["sales_file"]
        inventory_file = request.files["inventory_file"]

        # ===================================
        # FILE EXTENSIONS
        # ===================================

        sales_extension = os.path.splitext(
            sales_file.filename
        )[1]

        inventory_extension = os.path.splitext(
            inventory_file.filename
        )[1]

        # ===================================
        # SAVE FILES
        # ===================================

        sales_path = os.path.join(
            UPLOAD_FOLDER,
            "sales_upload" + sales_extension
        )

        inventory_path = os.path.join(
            UPLOAD_FOLDER,
            "inventory_upload" + inventory_extension
        )

        sales_file.save(sales_path)
        inventory_file.save(inventory_path)

        # ===================================
        # READ SALES FILE
        # ===================================

        if sales_extension == ".csv":

            sales_df = pd.read_csv(
                sales_path
            )

        else:

            sales_df = pd.read_excel(
                sales_path,
                engine="openpyxl"
            )

        # ===================================
        # READ INVENTORY FILE
        # ===================================

        if inventory_extension == ".csv":

            inventory_df = pd.read_csv(
                inventory_path
            )

        else:

            inventory_df = pd.read_excel(
                inventory_path,
                engine="openpyxl"
            )

        # ===================================
        # SALES COLUMNS
        # D = SKU
        # E = QUANTITY
        # ===================================

        sales_df = sales_df.iloc[:, [3, 4]]

        sales_df.columns = [
            "SKU",
            "Quantity"
        ]

        sales_df = sales_df.dropna()

        # ===================================
        # GROUP SALES
        # ===================================

        sales_summary = (
            sales_df.groupby("SKU")["Quantity"]
            .sum()
            .reset_index()
        )

        # ===================================
        # AVG DAILY SALES
        # ===================================

        sales_summary["ADS"] = (
            sales_summary["Quantity"] / 60
        )

        # ===================================
        # SORT DESCENDING
        # ===================================

        sales_summary = sales_summary.sort_values(
            by="Quantity",
            ascending=False
        )

        # ===================================
        # PARETO %
        # ===================================

        total_sales = (
            sales_summary["Quantity"]
            .sum()
        )

        sales_summary["Pareto"] = (
            sales_summary["Quantity"]
            .cumsum()
            / total_sales
        )

        # ===================================
        # ABC ANALYSIS
        # ===================================

        def abc_category(x):

            if x < 0.7:

                return "A"

            elif x > 0.9:

                return "C"

            else:

                return "B"

        sales_summary["ABC"] = (
            sales_summary["Pareto"]
            .apply(abc_category)
        )

        # ===================================
        # NEXT 7 DAYS
        # ===================================

        sales_summary["Next_7_Days"] = (
            sales_summary["ADS"] * 7
        )

        # ===================================
        # INVENTORY COLUMNS
        # C = SKU
        # M = INVENTORY
        # ===================================

        inventory_df = inventory_df.iloc[:, [2, 12]]

        inventory_df.columns = [
            "SKU",
            "Inventory"
        ]

        inventory_df = inventory_df.dropna()

        # ===================================
        # MERGE
        # ===================================

        master_df = pd.merge(
            sales_summary,
            inventory_df,
            on="SKU",
            how="left"
        )

        master_df["Inventory"] = (
            master_df["Inventory"]
            .fillna(0)
        )

        # ===================================
        # BUFFER DAYS
        # ===================================

        def buffer_days(x):

            if x == "A":

                return 4

            elif x == "B":

                return 2

            else:

                return 1

        master_df["Buffer_Days"] = (
            master_df["ABC"]
            .apply(buffer_days)
        )

        # ===================================
        # STOCK REQUIRED
        # ===================================

        master_df["Stock_Required"] = (
            (
                master_df["Next_7_Days"]
                +
                (
                    master_df["Buffer_Days"]
                    *
                    master_df["ADS"]
                )
            )
            -
            master_df["Inventory"]
        ).round()

        # ===================================
        # OPEN DASHBOARD
        # ===================================

        return render_template(
            "dashboard.html",
            results=None
        )

    except Exception as e:

        return f"Error: {str(e)}"

# ======================================
# BULK SEARCH
# ======================================

@app.route("/bulk_search", methods=["POST"])
def bulk_search():

    global master_df

    sku_text = request.form["sku_list"]

    sku_list = [
        x.strip().upper()
        for x in sku_text.splitlines()
        if x.strip() != ""
    ]

    results = []

    for sku in sku_list:

        result_df = master_df[
            master_df["SKU"]
            .astype(str)
            .str.upper()
            ==
            sku
        ]

        # SKU NOT FOUND
        if result_df.empty:

            results.append({

                "SKU": sku,

                "Inventory": 0,

                "ABC": "Not Found",

                "Stock_Required": 0

            })

        else:

            row = result_df.iloc[0]

            results.append({

                "SKU": row["SKU"],

                "Inventory": row["Inventory"],

                "ABC": row["ABC"],

                "Stock_Required": row["Stock_Required"]

            })

    return render_template(
        "dashboard.html",
        results=results
    )

# ======================================
# SAVE FINAL DISPATCH
# ======================================

@app.route("/save_dispatch", methods=["POST"])
def save_dispatch():

    sku_list = request.form.getlist("sku")

    qty_list = request.form.getlist("final_qty")

    dispatch_rows = []

    for sku, qty in zip(sku_list, qty_list):

        dispatch_rows.append({

            "SKU": sku,

            "Final_Qty": qty

        })

    dispatch_df = pd.DataFrame(
        dispatch_rows
    )

    output_path = os.path.join(
        OUTPUT_FOLDER,
        "final_dispatch.csv"
    )

    dispatch_df.to_csv(
        output_path,
        index=False
    )

    return render_template(
        "dashboard.html",
        results=None
    )

# ======================================
# DOWNLOAD MASTER CSV
# ======================================

@app.route("/download_master")
def download_master():

    global master_df

    output_path = os.path.join(
        OUTPUT_FOLDER,
        "master_calculation.csv"
    )

    master_df.to_csv(
        output_path,
        index=False
    )

    return send_file(
        output_path,
        as_attachment=True
    )

# ======================================
# DOWNLOAD FINAL CSV
# ======================================

@app.route("/download_final")
def download_final():

    output_path = os.path.join(
        OUTPUT_FOLDER,
        "final_dispatch.csv"
    )

    return send_file(
        output_path,
        as_attachment=True
    )

# ======================================
# RUN APP
# ======================================

if __name__ == "__main__":

    app.run(debug=True)