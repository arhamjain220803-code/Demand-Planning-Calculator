from flask import Flask, render_template, request, send_file
import pandas as pd
import os
from werkzeug.utils import secure_filename

app = Flask(__name__)

UPLOAD_FOLDER = "uploads"
OUTPUT_FOLDER = "output"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

master_data = None
item_master_global = None
manual_entries = []
current_results = []

# =========================================
# HOME
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
    global manual_entries
    global item_master_global

    try:

        manual_entries = []

        sales_file = request.files["sales_file"]
        inventory_file = request.files["inventory_file"]

        sales_path = os.path.join(
            UPLOAD_FOLDER,
            secure_filename(sales_file.filename)
        )

        inventory_path = os.path.join(
            UPLOAD_FOLDER,
            secure_filename(inventory_file.filename)
        )

        sales_file.save(sales_path)
        inventory_file.save(inventory_path)

        # =========================================
        # READ SALES FILE
        # =========================================

        if sales_path.endswith(".csv"):

            sales_df = pd.read_csv(sales_path)

        else:

            sales_df = pd.read_excel(
                sales_path,
                engine="openpyxl"
            )

        # D and E columns
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
        # GROUP SALES
        # =========================================

        sales_summary = (
            sales_df.groupby("SKU")["Quantity"]
            .sum()
            .reset_index()
        )

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
        # INVENTORY FILE
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

        inventory_df["SKU"] = (
            inventory_df["SKU"]
            .astype(str)
            .str.upper()
            .str.strip()
        )

        # =========================================
        # ITEM MASTER
        # =========================================

        master_file = "master/item_master.xlsx"

        if master_file.endswith(".csv"):

            item_master = pd.read_csv(master_file)

        else:

            item_master = pd.read_excel(
                master_file,
                engine="openpyxl"
            )

        item_master = item_master.iloc[:, [1, 2]]

        item_master.columns = [
            "SKU",
            "Item_Name"
        ]

        item_master["SKU"] = (
            item_master["SKU"]
            .astype(str)
            .str.upper()
            .str.strip()
        )
        item_master_global = item_master.copy()

        # =========================================
        # MERGE USING ITEM MASTER AS BASE
        # =========================================

        master_df = item_master.copy()
        master_df = pd.merge(
            master_df,
            sales_summary,
            on="SKU",
            how="left"
        )

        master_df = pd.merge(
            master_df,
            inventory_df,
            on="SKU",
            how="left"
        )

        master_df["Quantity"] = master_df["Quantity"].fillna(0)
        master_df["Inventory"] = master_df["Inventory"].fillna(0)
        master_df["Avg_Per_Day"] = master_df["Avg_Per_Day"].fillna(0)
        master_df["Pareto"] = master_df["Pareto"].fillna(0)
        master_df["ABC"] = master_df["ABC"].fillna("-")
        master_df["Weighted_Avg"] = master_df["Weighted_Avg"].fillna(0)
        master_df["Next_7_Days"] = master_df["Next_7_Days"].fillna(0)

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

        # SAVE MASTER CSV

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
    global manual_entries
    global current_results

    sku_text = request.form["sku_list"]

    sku_list = [
    sku.strip().upper()
    for sku in sku_text.splitlines()
    if sku.strip()
    ]

    # Remove duplicates but keep order
    sku_list = list(dict.fromkeys(sku_list))

    filtered = master_data[
        master_data["SKU"]
        .astype(str)
        .str.upper()
        .isin(sku_list)
    ].copy()

    # Keep same order as typed
    filtered["Sort_Order"] = filtered["SKU"].apply(
        lambda x: sku_list.index(
            str(x).upper()
        )
    )

    filtered = filtered.sort_values(
        by="Sort_Order"
    )

    filtered = filtered.drop(
        columns=["Sort_Order"]
    )

    results = filtered.to_dict(
        orient="records"
    )

    # Add SKUs not found in master
    found_skus = set(
        filtered["SKU"]
        .astype(str)
        .str.upper()
    )

    for sku in sku_list:

        if sku not in found_skus:

            results.append({

                "SKU": sku,
                "Item_Name": "SKU Not Found",
                "Inventory": "",
                "ABC": "MANUAL",
                "Stock_Required": ""

            })
            
            
            

    # ADD MANUAL ENTRIES ALSO
    results = manual_entries + results

    current_results = results

    return render_template(
        "dashboard.html",
        results=results
 )

# =========================================
# MANUAL SKU
# =========================================

@app.route("/add_manual", methods=["POST"])
def add_manual():

    global manual_entries
    global master_data
    global current_results
    global item_master_global

    sku = request.form[
        "manual_sku"
    ].upper()

    qty = request.form[
        "manual_qty"
    ]

    # FIND ITEM NAME FROM MASTER
    item_name = "Manual Entry"

    row = item_master_global[
    item_master_global["SKU"] == sku
    ]

    if not row.empty:

        item_name = row.iloc[0][
            "Item_Name"
        ]

    manual_row = {

        "SKU": sku,
        "Item_Name": item_name,
        "Inventory": "",
        "ABC": "MANUAL",
        "Stock_Required": qty

    }

    # ADD TO MANUAL LIST
    manual_entries.append(manual_row)

    # APPEND TO CURRENT TABLE
    current_results.append(manual_row)

    return render_template(
        "dashboard.html",
        results=current_results
    )

# =========================================
# SAVE FINAL CSV
# =========================================

@app.route("/save_dispatch", methods=["POST"])
def save_dispatch():

    global master_data
    global manual_entries

    skus = request.form.getlist("sku")
    qtys = request.form.getlist("final_qty")

    dispatch_list = []

    # MANUAL ENTRIES FIRST
    for row in manual_entries:

        dispatch_list.append({

            "SKU": row["SKU"],
            "Item_Name": row["Item_Name"],
            "Final_Qty": row["Stock_Required"]

        })

    # NORMAL ENTRIES
    for sku, qty in zip(skus, qtys):

        if qty.strip() == "":
            continue

        if float(qty) == 0:
            continue

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
# DOWNLOAD MASTER
# =========================================

@app.route("/download_master")
def download_master():

    return send_file(
        os.path.join(
            OUTPUT_FOLDER,
            "replenishment_output.csv"
        ),
        as_attachment=True
    )

# =========================================
# DOWNLOAD FINAL
# =========================================

@app.route("/download_final")
def download_final():

    return send_file(
        os.path.join(
            OUTPUT_FOLDER,
            "final_dispatch.csv"
        ),
        as_attachment=True
    )

# =========================================
# RUN
# =========================================

if __name__ == "__main__":

    app.run(debug=True)