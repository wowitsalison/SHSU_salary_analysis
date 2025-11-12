from urllib.parse import urljoin, quote, unquote
from bs4 import BeautifulSoup
from pathlib import Path
from io import BytesIO
import pandas as pd
import requests
import re

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

# Set up dataframe to collect all salaries
all_deans = pd.DataFrame(columns=["Year", "Title", "Name", "Salary"])

# -------- Normalization helper functions --------

# Normalize column names
def normalize_col(col):
    if pd.isna(col):
        return ""
    return re.sub(r'\s+|[^a-zA-Z0-9]', '', str(col).lower())

# Normalize dean titles
def normalize_dean_title(title, dept=None):
    if not isinstance(title, str):
        return title
    title_clean = title.strip()

    # If title already specifies college, leave as is
    if re.search(r'\bdean\b.*\b(com|coe|coba|chss|cj|cam|coset|cohs)\b', title_clean, re.IGNORECASE) \
       or re.search(r'\bdean\b.*\b(osteopathic|education|business|humanit|criminal|arts|science|health)\b', title_clean, re.IGNORECASE):
        return title_clean
    
    # If "Dean of College", use department if available
    if re.search(r'\bdean\b', title_clean, re.IGNORECASE) and re.search(r'\bcollege\b', title_clean, re.IGNORECASE) and dept:
        dept_str = str(dept).strip()

        if dept_str and dept_str.lower() not in ["nan", "none", ""]:
            # Map department named to abbreviations
            abbreviations = {
                "cam office of the dean" : "CAM",
                "office of the dean ce" : "COE",
                "chss office of the dean" : "CHSS",
                "coba office of the dean" : "COBA",
                "coset office of the dean" : "COSET",
                "cohs office of the dean" : "COHS",
                "college of criminal justice" : "CJ"
            }

            # Normalize dept string for matching
            dept_norm = dept_str.lower()
            # If the dept is already an abbreviation (e.g., "COM", "COE"), accept it
            if re.fullmatch(r'[A-Z]{2,6}', dept_str) or re.fullmatch(r'[a-z]{2,6}', dept_str):
                # preserve uppercase
                return f"Dean {dept_str.upper()}"

            # Try exact mapping or substring mapping
            found = None
            for full, abbr in abbreviations.items():
                if full in dept_norm or re.search(re.escape(full), dept_norm, re.IGNORECASE):
                    found = abbr
                    break

            if not found:
                # If dept looks like "College of X", attempt to extract acronym from capital letters or words
                # e.g., "College of Education" -> "COE"; fallback: take initials
                words = re.findall(r'[A-Za-z]+', dept_str)
                initials = ''.join(w[0].upper() for w in words if len(w) > 0)[:4]
                if len(initials) >= 2:
                    found = initials
                else:
                    found = dept_str  # fallback: use the raw dept string

            return f"Dean {found}"

    # If title looks like 'Dean College Health Sciences' (no 'of'), try to treat as generic and use dept if present
    if re.search(r'\bdean\b.*\bcollege\b', title_clean, re.IGNORECASE) and dept:
        return normalize_dean_title("Dean of College", dept)

    return title_clean

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
        year = None

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

    # Only process the first sheet of each file
    sheet_name = xls.sheet_names[0]

    # Standardize column names
    col_map = {
        "positiontitle": "Title",
        "jobtitle": "Title",
        "title": "Title",
        "employeename": "Name",
        "name": "Name",
        "annualsalary": "Salary",
        "salary": "Salary",
        "annualpayrate": "Salary",
        "fy18annualsalary": "Salary",
        "fy19annualsalary": "Salary",
    }

    # Attempt to read the sheet with different header rows
    df = None
    for header_row in range(10):
        try:
            df_try = pd.read_excel(
                xls,
                sheet_name=sheet_name,
                header=header_row,
                engine=xls.engine
            )

            # Normalize columns
            normalized_cols = [normalize_col(c) for c in df_try.columns]
            
            # Map to standard columns
            mapped_cols = [col_map.get(c, c) for c in normalized_cols]
            df_try.columns = mapped_cols

            # Check if essential columns exist
            if all(col in df_try.columns for col in ["Title", "Name", "Salary"]):
                df = df_try
                break

        except Exception:
            continue

    if df is None:
        print(f"Skipping {url} — could not detect header row in sheet {sheet_name}")
        sample = pd.read_excel(xls, sheet_name=sheet_name, nrows=10, engine=xls.engine)
        print(sample.head())
        continue

    # -------- Normalize titles --------

    df["Title"] = df["Title"].astype(str).str.strip()

    # Filter to rows where first word of Title is "Dean"
    filtered = df[df["Title"].str.match(r"^Dean\b", case=False, na=False)]
    filtered = filtered[~filtered["Title"].str.contains("Dean's Office Specialist", case=False, na=False)]

    if filtered.empty:
        continue

    # Detect department/college column
    dept_col = None
    dept_candidates = {"department", "dept", "college", "division", "unit", "school"}
    for col in filtered.columns:
        nc = normalize_col(col)  # normalized column name (lower, no spaces/punct)
        # If the normalized name matches a candidate or contains 'college' or 'dept', pick it
        if nc in dept_candidates or "college" in nc or nc.startswith("dept"):
            dept_col = col
            break

    # Apply normalization for dean titles
    if dept_col:
        # Use the actual column name found (not normalized) when looking up values
        filtered["Title"] = filtered.apply(
            lambda row: normalize_dean_title(row["Title"], row.get(dept_col)), axis=1
        )
    else:
        # No department column found; still try to normalize known patterns in the title itself
        filtered["Title"] = filtered["Title"].apply(lambda t: normalize_dean_title(t, None))

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