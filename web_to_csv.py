from bs4 import BeautifulSoup
import requests
import pandas as pd
import re
from io import BytesIO
from urllib.parse import urljoin, quote, unquote
from pathlib import Path

# Home page URL
url = "https://profiles.shsu.edu/sms049/Images/Salary.html"
# Set a user-agent to mimic a browser
headers = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/58.0.3029.110 Safari/537.3"
    )
}

# Fetch the HTML
home_response = requests.get(url, headers=headers)
home_response.raise_for_status()
soup = BeautifulSoup(home_response.text, "html.parser")

# Get all links from <a> html tags
all_links = [a["href"] for a in soup.find_all("a", href=True)]

# Get format patterns for new sheets and old sheets
full_time_pattern = re.compile(r"Full\s*Time\s*Employee", re.IGNORECASE)
old_year_pattern = re.compile(r"FY\s?\d{4}\.xlsx?$", re.IGNORECASE)

# Filter links for full-time employee Excel files
ft_links = [
    link
    for link in all_links
    if link.lower().endswith((".xlsx", ".xls"))
    and (full_time_pattern.search(link) or old_year_pattern.search(link))
]

# Fix the links: resolve "../" and encode spaces properly
ft_links = [quote(urljoin(url, link), safe=":/") for link in ft_links]

with open("full_time_employee_links.txt", "w") as f:
    for link in ft_links:
        f.write(link + "\n")

print("Links saved to full_time_employee_links.txt")

all_deans = pd.DataFrame(columns=["Year", "Title", "Name", "Salary"])

for url in ft_links:
    print(f"Processing {url}")
    year_match = re.search(r'FY\s?(\d{2,4})', url, re.IGNORECASE)
    year = year_match.group(1) if year_match else "Unknown"

    try:
        response = requests.get(url)
        response.raise_for_status()
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        continue

    # Try both engines
    try:
        xls = pd.ExcelFile(BytesIO(response.content), engine="openpyxl")
    except Exception:
        try:
            xls = pd.ExcelFile(BytesIO(response.content), engine="xlrd")
        except Exception as e:
            print(f"Could not open {url} with any engine: {e}")
            continue

    for sheet_name in xls.sheet_names:
        try:
            df = pd.read_excel(xls, sheet_name=sheet_name, engine=xls.engine)
        except Exception as e:
            print(f"Error reading sheet {sheet_name} from {url}: {e}")
            continue

        # Convert non-string headers to strings safely
        df.columns = [
            str(col).strip().replace("\n", " ").replace("\r", "").title()
            for col in df.columns
        ]

        # Handle different naming conventions
        col_map = {
            "Position_Title": "Title",
            "Home_Organization_Desc": "Department",
            "Annual_Salary": "Salary",
            "Employee_Name": "Name",
        }

        df.rename(columns=col_map, inplace=True)

        # Detect and skip summary/title rows
        if df.shape[1] < 3 or not any("Title" in c for c in df.columns):
            print(f"Skipping {url} — missing expected columns: {df.columns.tolist()}")
            continue

        # Filter to only keep rows where the first word of the title is "Dean"
        df["Title"] = df["Title"].astype(str).str.strip()
        filtered = df[df["Title"].str.match(r"^Dean\b", case=False, na=False)]

        # Remove 'Dean's Office Specialist' rows
        filtered = filtered[~filtered["Title"].str.contains("Dean's Office Specialist", case=False, na=False)]

        if filtered.empty:
            continue

        # Extract fiscal year from filename
        filename = Path(unquote(url)).name  # Decode %20 etc.
        match = re.search(r'FY[\s_]*(\d{2,4})', filename, re.IGNORECASE)
        if match:
            year_str = match.group(1)
            if len(year_str) == 2:
                year = int("20" + year_str)
            else:
                year = int(year_str)
        else:
            year = None

        df["Year"] = year

        filtered["Year"] = year
        if "Name" in filtered.columns and "Salary" in filtered.columns:
            all_deans = pd.concat(
                [all_deans, filtered[["Year", "Title", "Name", "Salary"]]],
                ignore_index=True
            )
        else:
            print(f"Skipping {url} — after filtering, missing Name or Salary columns.")
            
# Save to CSV
all_deans.to_csv("deans_salaries.csv", index=False)
print("All Dean salaries saved to deans_salaries.csv")
