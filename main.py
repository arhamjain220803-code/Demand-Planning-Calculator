from flask import Flask, render_template, request, send_file
import pandas as pd
import os
from werkzeug.utils import secure_filename

app = Flask(__name__)

UPLOAD_FOLDER = "uploads"
OUTPUT_FOLDER = "output"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# =========================================
# GLOBAL STORAGE
# =========================================

master_data = None
final_dispatch_data = []

# =========================================
# HOME PAGE
# =========================================

@app.route("/")
def home():
    return render_template("index.html")

# =========================================
# UPLOAD FILES
# =========================================

@app.route("/upload", methods=["POST"])
def upload_files():

    global master_data

    try:

        sales_file = request.files["sales_file"]
        inventory_file = request.files["inventory_file"]

        sales_filename = secure_filename(sales_file.filename)
        inventory_filename = secure_filename(inventory_file.filename)

        sales_path = os.path.join(
            UPLOAD_FOLDER,
            sales_filename
        )

        inventory_path = os.path.join(
            UPLOAD_FOLDER,
            inventory_filename
        )

        sales_file.save(sales_path)
        inventory_file.save(inventory_path)

        # =========================================
        # READ SALES FILE
        # D = SKU
        # E = TOTAL QTY
        # =========================================

        sales_df = pd.read_excel(
            sales_path,
            sheet_name="data(7)",
            engine="openpyxl"
        )

        sales_df = sales_df.iloc[:, [3, 4]]

        sales_df.columns = [
            "SKU",
            "Quantity"
        ]

        sales_df = sales_df.dropna()

        sales_df["SKU"] = (
            sales_df["SKU"]
            .astype(str)
            .str.upper()
            .str.strip()
        )

        sales_df["Quantity"] = pd.to_numeric(
            sales_df["Quantity"],
            errors="coerce"
        )

        # =========================================
        # SALES SUMMARY
        # =========================================

        sales_summary = (
            sales_df.groupby("SKU")["Quantity"]
            .sum()
            .reset_index()
        )

        # =========================================
        # DEMAND CALCULATION
        # =========================================

        DAYS = 60

        sales_summary["Avg_Per_Day"] = (
            sales_summary["Quantity"] / DAYS
        )

        sales_summary = sales_summary.sort_values(
            by="Quantity",
            ascending=False
        )

        total_qty = sales_summary["Quantity"].sum()

        sales_summary["Pareto"] = (
            sales_summary["Quantity"].cumsum()
            / total_qty
        )

        sales_summary["ABC"] = sales_summary[
            "Pareto"
        ].apply(
            lambda x:
            "A" if x < 0.7
            else (
                "C" if x > 0.9
                else "B"
            )
        )

        sales_summary["Weighted_Avg"] = (
            sales_summary["Avg_Per_Day"]
        )

        sales_summary["Next_7_Days"] = (
            sales_summary["Weighted_Avg"] * 7
        )

        # =========================================
        # READ INVENTORY FILE
        # C = SKU
        # M = INVENTORY
        # =========================================

        if inventory_path.endswith(".csv"):

            inventory_df = pd.read_csv(
                inventory_path
            )

        else:

            inventory_df = pd.read_excel(
                inventory_path,
                engine="openpyxl"
            )

        inventory_df = inventory_df.iloc[:, [2, 12]]

        inventory_df.columns = [
            "SKU",
            "Inventory"
        ]

        inventory_df = inventory_df.dropna()

        inventory_df["SKU"] = (
            inventory_df["SKU"]
            .astype(str)
            .str.upper()
            .str.strip()
        )

        # =========================================
        # READ ITEM MASTER
        # B = SKU
        # C = ITEM NAME
        # =========================================

        item_master = pd.read_excel(
            "master/item_master.xlsx",
            engine="openpyxl"
        )

        item_master = item_master.iloc[:, [1, 2]]

        item_master.columns = [
            "SKU",
            "Item_Name"
        ]

        item_master = item_master.dropna()

        item_master["SKU"] = (
            item_master["SKU"]
            .astype(str)
            .str.upper()
            .str.strip()
        )

        # =========================================
        # MERGE SALES + INVENTORY
        # =========================================

        master_df = pd.merge(
            sales_summary,
            inventory_df,
            on="SKU",
            how="left"
        )

        # =========================================
        # MERGE ITEM MASTER
        # =========================================

        master_df = pd.merge(
            master_df,
            item_master,
            on="SKU",
            how="left"
        )

        master_df["Inventory"] = (
            master_df["Inventory"]
            .fillna(0)
        )

        # =========================================
        # STOCK REQUIRED
        # =========================================

        def calculate_stock(row):

            if row["ABC"] == "A":
                factor = 4

            elif row["ABC"] == "B":
                factor = 2

            else:
                factor = 1

            return (
                row["Next_7_Days"]
                + (
                    factor
                    * row["Weighted_Avg"]
                )
                - row["Inventory"]
            )

        master_df["Stock_Required"] = (
            master_df.apply(
                calculate_stock,
                axis=1
            )
        )

        master_df["Stock_Required"] = (
            master_df["Stock_Required"]
            .round(0)
            .astype(int)
        )

        # =========================================
        # SAVE MASTER CSV
        # =========================================

        output_path = os.path.join(
            OUTPUT_FOLDER,
            "replenishment_output.csv"
        )

        master_df.to_csv(
            output_path,
            index=False
        )

        master_data = master_df

        return render_template(
            "dashboard.html",
            results=[]
        )

    except Exception as e:

        return f"Error: {str(e)}"

# =========================================
# BULK SEARCH
# =========================================

@app.route("/bulk_search", methods=["POST"])
def bulk_search():

    global master_data

    if master_data is None:
        return "Please upload files first."

    sku_text = request.form["sku_list"]

    sku_list = [
        sku.strip().upper()
        for sku in sku_text.splitlines()
        if sku.strip()
    ]

    filtered = master_data[
        master_data["SKU"].isin(sku_list)
    ]

    return render_template(
        "dashboard.html",
        results=filtered.to_dict(
            orient="records"
        )
    )

# =========================================
# SAVE FINAL DISPATCH
# =========================================

@app.route("/save_dispatch", methods=["POST"])
def save_dispatch():

    global final_dispatch_data

    skus = request.form.getlist("sku")
    qtys = request.form.getlist("final_qty")

    dispatch_list = []

    for sku, qty in zip(skus, qtys):

        item_row = master_data[
            master_data["SKU"] == sku
        ]

        item_name = ""

        if not item_row.empty:
            item_name = item_row.iloc[0][
                "Item_Name"
            ]

        dispatch_list.append({

            "SKU": sku,
            "Item_Name": item_name,
            "Final_Qty": qty

        })

    dispatch_df = pd.DataFrame(
        dispatch_list
    )

    final_dispatch_data = dispatch_df

    output_path = os.path.join(
        OUTPUT_FOLDER,
        "final_dispatch.csv"
    )

    dispatch_df.to_csv(
        output_path,
        index=False
    )

    return send_file(
        output_path,
        as_attachment=True
    )

# =========================================
# ADD MANUAL SKU
# =========================================

@app.route("/add_manual", methods=["POST"])
def add_manual():

    global final_dispatch_data

    manual_sku = request.form[
        "manual_sku"
    ].upper()

    manual_qty = request.form[
        "manual_qty"
    ]

    item_name = ""

    if master_data is not None:

        row = master_data[
            master_data["SKU"]
            == manual_sku
        ]

        if not row.empty:

            item_name = row.iloc[0][
                "Item_Name"
            ]

    new_row = pd.DataFrame([{

        "SKU": manual_sku,
        "Item_Name": item_name,
        "Final_Qty": manual_qty

    }])

    if isinstance(
        final_dispatch_data,
        list
    ):

        final_dispatch_data = new_row

    else:

        final_dispatch_data = pd.concat(
            [
                final_dispatch_data,
                new_row
            ],
            ignore_index=True
        )

    output_path = os.path.join(
        OUTPUT_FOLDER,
        "final_dispatch.csv"
    )

    final_dispatch_data.to_csv(
        output_path,
        index=False
    )

    return render_template(
        "dashboard.html",
        results=[]
    )

# =========================================
# DOWNLOAD MASTER CSV
# =========================================

@app.route("/download_master")
def download_master():

    output_path = os.path.join(
        OUTPUT_FOLDER,
        "replenishment_output.csv"
    )

    return send_file(
        output_path,
        as_attachment=True
    )

# =========================================
# DOWNLOAD FINAL CSV
# =========================================

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

# =========================================
# RUN APP
# =========================================

if __name__ == "__main__":

    app.run(debug=True)