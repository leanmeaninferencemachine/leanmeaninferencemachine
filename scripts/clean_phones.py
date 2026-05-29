#!/usr/bin/env python3
"""
Phone Cleaner for WhatsApp Bulk Sender.
Input: Excel with [Student Name] | [Parent Phone]
Output: CSV with [First Name] | [Cleaned Phone (+52...)]
Rules:
1. Keep only First Name.
2. Remove ALL non-digit chars from phone (spaces, dashes, letters).
3. Delete row if phone is empty or invalid.
4. Auto-add +52 (Mexico) if missing and length is 10 digits.
"""
import pandas as pd
import sys
import os
import re

def clean_phones(input_file, output_file="data/whatsapp_contacts.csv", country_code="52"):
    if not os.path.exists(input_file):
        print(f"❌ Error: File '{input_file}' not found.")
        sys.exit(1)

    print(f"📂 Loading {input_file}...")
    try:
        df = pd.read_excel(input_file)
    except Exception as e:
        print(f"❌ Error reading Excel: {e}")
        sys.exit(1)

    # Normalize headers (lowercase, strip)
    df.columns = df.columns.str.lower().str.strip()
    
    # Identify Columns (Assume Col 0 = Name, Col 1 = Phone)
    # We explicitly rename them to 'name' and 'phone' for consistency
    col_list = list(df.columns)
    if len(col_list) < 2:
        print("❌ Error: Excel must have at least 2 columns (Name, Phone).")
        sys.exit(1)
        
    df.rename(columns={col_list[0]: 'name', col_list[1]: 'phone'}, inplace=True)

    print(f"📊 Original rows: {len(df)}")

    # 1. Drop rows where Phone is empty/NaN
    initial_count = len(df)
    df = df.dropna(subset=['phone'])
    print(f"   - Dropped {initial_count - len(df)} empty phone rows.")

    # 2. Convert Phone to String and Remove NON-DIGITS
    # This removes spaces, dashes, parentheses, AND letters.
    df['phone'] = df['phone'].astype(str).str.replace(r'\D', '', regex=True)

    # 3. Validate: Must be digits only and reasonable length (7-15)
    # If it was "abc123", it becomes "123". If it was "abc", it becomes "" (empty).
    def is_valid_phone(p):
        if not p or p == 'nan':
            return False
        # Must be all digits now (since we removed non-digits)
        # Check length: Mexico mobile is 10 digits (without code) or 12 (with 52)
        return 7 <= len(p) <= 15

    initial_count = len(df)
    df = df[df['phone'].apply(is_valid_phone)]
    dropped_invalid = initial_count - len(df)
    if dropped_invalid > 0:
        print(f"   - Dropped {dropped_invalid} rows with invalid/short phones.")

    # 4. Homogenize Country Code (+52)
    def normalize_phone(p):
        p = str(p).strip()
        # If already starts with +52 or 52 (and length is 12), keep it
        if p.startswith('+52'):
            return p
        if p.startswith('52') and len(p) == 12:
            return '+' + p
        
        # If it's 10 digits (standard MX mobile), add +52
        if len(p) == 10:
            return f"+{country_code}{p}"
        
        # If it's 11 digits (sometimes people add a '1' or '0'), try to fix
        if len(p) == 11 and p.startswith('1'):
            return f"+{country_code}{p[1:]}"
            
        # Fallback: Just add + and code if unsure, but warn
        return f"+{country_code}{p}"

    df['phone'] = df['phone'].apply(normalize_phone)

    # 5. Clean Names: Extract First Name Only
    df['name'] = df['name'].astype(str).str.strip()
    df['name'] = df['name'].apply(lambda x: x.split()[0] if x and x != 'nan' else 'Padre de Familia')

    # 6. Final Save
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    final_df = df[['name', 'phone']]
    final_df.to_csv(output_file, index=False)

    print(f"✅ Cleaning Complete!")
    print(f"   - Valid contacts: {len(final_df)}")
    print(f"   - Output: {output_file}")
    print(f"\n👀 Preview:")
    print(final_df.head())

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/clean_phones.py <path_to_excel.xlsx>")
        print("Example: python3 scripts/clean_phones.py data/parents_list.xlsx")
        sys.exit(1)
    
    input_path = sys.argv[1]
    clean_phones(input_path)
