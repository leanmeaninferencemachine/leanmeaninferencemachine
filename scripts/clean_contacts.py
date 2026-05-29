#!/usr/bin/env python3
"""
Contact Cleaner: Converts Excel to Clean CSV for Bulk Emailing.
Handles merged cells, floats, NaNs, and messy formatting.
"""
import pandas as pd
import sys
import os

def clean_contacts(input_file, output_file="data/ex_clients.csv"):
    if not os.path.exists(input_file):
        print(f"❌ Error: File '{input_file}' not found.")
        sys.exit(1)

    print(f"📂 Loading {input_file}...")
    try:
        # Load Excel. fillna(method='ffill') helps if names are in merged cells spanning rows
        df = pd.read_excel(input_file)
        
        # Forward-fill NaNs in case of merged cells in the Name column
        # This copies "John Doe" down to rows where the name cell was visually merged but empty in data
        if 'Nombre del Alumno' in df.columns or df.columns[0] == 'Nombre del Alumno':
             # Identify name column index dynamically if headers are messy
            name_col = 0
            df.iloc[:, name_col] = df.iloc[:, name_col].fillna(method='ffill')
            
    except Exception as e:
        print(f"❌ Error reading Excel: {e}")
        sys.exit(1)

    # Normalize column names (lowercase, strip spaces)
    df.columns = df.columns.str.lower().str.strip()
    
    # Map common Spanish headers to standard 'name' and 'email'
    col_mapping = {}
    if 'nombre del alumno' in df.columns:
        col_mapping['nombre del alumno'] = 'name'
    elif df.columns[0] != 'name':
        col_mapping[df.columns[0]] = 'name'
        
    if 'e-mail' in df.columns:
        col_mapping['e-mail'] = 'email'
    elif 'email' in df.columns:
        col_mapping['email'] = 'email'
    elif len(df.columns) > 1 and df.columns[1] != 'email':
        col_mapping[df.columns[1]] = 'email'
        
    df.rename(columns=col_mapping, inplace=True)

    # Ensure we have 'name' and 'email' columns now
    if 'name' not in df.columns or 'email' not in df.columns:
        print(f"❌ Could not identify Name/Email columns. Found: {list(df.columns)}")
        sys.exit(1)

    print(f"📊 Original rows: {len(df)}")

    # 1. Drop rows where Email is physically empty/NaN
    initial_count = len(df)
    df = df.dropna(subset=['email'])
    print(f"   - Dropped {initial_count - len(df)} empty email rows.")

    # 2. Force Email to String and Validate '@'
    df['email'] = df['email'].astype(str)
    initial_count = len(df)
    df = df[df['email'].str.contains('@', na=False)]
    dropped_invalid = initial_count - len(df)
    if dropped_invalid > 0:
        print(f"   - Dropped {dropped_invalid} rows with invalid emails (no '@').")

    # 3. CRITICAL FIX: Safe Name Processing
    # We define a safe function that handles ANY type (float, int, str, None)
    def safe_get_first_name(val):
        # If it's a float (e.g. nan, or 1.0), convert to string first
        if isinstance(val, float):
            if pd.isna(val):
                return 'Friend'
            val = str(int(val)) # Convert 1.0 -> "1"
        elif val is None:
            return 'Friend'
        else:
            val = str(val).strip()
        
        if not val or val.lower() == 'nan':
            return 'Friend'
        
        # Split and take first word
        parts = val.split()
        return parts[0] if parts else 'Friend'

    # Apply the safe function
    df['name'] = df['name'].apply(safe_get_first_name)

    # 4. Clean Email strings (lowercase, strip)
    df['email'] = df['email'].str.strip().str.lower()

    # 5. Final Cleanup: Remove rows where name is just 'Friend' (optional, keep if you want)
    # df = df[df['name'] != 'Friend'] 
    
    # Select only needed columns
    final_df = df[['name', 'email']]

    # Save to CSV
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    final_df.to_csv(output_file, index=False)

    print(f"✅ Cleaning Complete!")
    print(f"   - Valid contacts saved: {len(final_df)}")
    print(f"   - Output file: {output_file}")
    print(f"\n👀 Preview:")
    print(final_df.head())

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/clean_contacts.py <path_to_excel_file.xlsx>")
        sys.exit(1)
    
    input_path = sys.argv[1]
    clean_contacts(input_path)