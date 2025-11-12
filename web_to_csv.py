from urllib.parse import urljoin, quote, unquote
from bs4 import BeautifulSoup
from pathlib import Path
from io import BytesIO
import pandas as pd
import requests
import re
import mappings

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

#Set up dataframe to collect all salaries
all_deans = pd.DataFrame(columns=["Year", "Title", "Name", "Salary"])

# -------- Grab and process all relevant links from the webpage --------

# Fetch the HTML
response = requests.get(url, headers=headers)
response.raise_for_status()
soup = BeautifulSoup(response.text, "html.parser")

# Get all links from <a> html tags
all_links = [a["href"] for a in soup.find_all("a", href=True)]

# Get format patterns for new sheets and old sheets
new_pattern = re.compile(r"Full\s*Time\s*Employee", re.IGNORECASE)
old_pattern = re.compile(r"FY\s?\d{4}\.xlsx?$", re.IGNORECASE)

# Filter links for full-time employee Excel files
ft_links = [
    link for link in all_links
    if link.lower().endswith((".xlsx", ".xls"))
    and (new_pattern.search(link) or old_pattern.search(link))
]

# Clean the links: resolve "../" and encode spaces properly
ft_links = [quote(urljoin(url, link), safe=":/") for link in ft_links]

# Remove all duplicates while preserving order
ft_links = list(dict.fromkeys(ft_links))

# -------- Normalization helper functions --------

# Normalize column names
def normalize_col(col):
    if pd.isna(col):
        return ""
    return re.sub(r'\s+|[^a-zA-Z0-9]', '', str(col).lower())

# Normalize dean titles
def normalize_dean_title(dept):
    if not isinstance(dept, str) or not dept.strip():
        return "Dean Unknown"
    dept_norm = re.sub(r'[^a-zA-Z0-9]', '', dept.lower())
    for full, abbr in mappings.abbreviations.items():
        if full in dept_norm:
            return f"Dean {abbr}"
    # fallback: take initials
    words = re.findall(r"[A-Za-z]+", dept)
    initials = ''.join(w[0].upper() for w in words if w)
    return f"Dean {initials or '?'}"

# -------- Process each Excel file --------

for url in ft_links:
    print(f"Processing {url}")

    # Extract year from filename
    filename = Path(unquote(url)).name
    match = re.search(r'FY[\s_]*(\d{2,4})', filename, re.IGNORECASE)
    if match:
        year_str = match.group(1)
        year = int("20" + year_str) if len(year_str) == 2 else int(year_str)
    else:
        print(f"Could not determine year from {filename}")
        continue

    # Fetch the Excel file
    try:
        response = requests.get(url)
        response.raise_for_status()
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        continue

    # Try both Excel engines for different formats
    try:
        xls = pd.ExcelFile(BytesIO(response.content), engine="openpyxl")
    except Exception:
        try:
            xls = pd.ExcelFile(BytesIO(response.content), engine="xlrd")
        except Exception as e:
            print(f"Could not open {url} with any engine: {e}")
            continue

    # Read the first sheet of each file
    sheet_name = xls.sheet_names[0]
    try:
        df = pd.read_excel(xls, sheet_name=sheet_name, engine=xls.engine)
    except Exception as e:
        print(f"Could not read {sheet_name} from {filename}: {e}")
        continue

    # Normalize columns
    df.columns = [normalize_col(c) for c in df.columns]

    # Get column names for this year
    title_col = normalize_col(mappings.title_columns_by_year.get(year)) if mappings.title_columns_by_year.get(year) else None
    dept_col = normalize_col(mappings.dept_columns_by_year.get(year)) if mappings.dept_columns_by_year.get(year) else None
    salary_col = normalize_col(mappings.salary_columns_by_year.get(year)) if mappings.salary_columns_by_year.get(year) else None
    name_col = "name"

    # Check for missing required columns
    missing_cols = [col for col in [title_col, name_col, salary_col] if not col or col not in df.columns]
    if missing_cols:
        print(f"Skipping {year}: missing required columns {missing_cols}")
        continue

    # Rename to consistent names
    rename_map = {}
    if title_col: rename_map[title_col] = "Title"
    if dept_col: rename_map[dept_col] = "Dept"
    if salary_col: rename_map[salary_col] = "Salary"
    rename_map[name_col] = "Name"
    df.rename(columns=rename_map, inplace=True)

    # Keep only rows containing "Dean"
    df = df[df["Title"].astype(str).str.contains(r"\bdean\b", case=False, na=False)]

    # Create simplified dean title
    if "Dept" in df.columns:
        df["Title"] = df["Dept"].apply(normalize_dean_title)
    else:
        df["Title"] = "Dean of College"

    # Add year
    df["Year"] = year

    # Keep only columns we need
    keep_cols = [c for c in ["Year", "Title", "Name", "Salary"] if c in df.columns]
    df = df[keep_cols]

    all_deans = pd.concat([all_deans, df], ignore_index=True)

# -------- Save to CSV --------

all_deans.to_csv("deans_salaries.csv", index=False)
print("All Dean salaries saved to deans_salaries.csv")