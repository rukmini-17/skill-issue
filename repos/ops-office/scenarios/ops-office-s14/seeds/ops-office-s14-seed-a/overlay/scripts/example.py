#!/usr/bin/env python3
"""
Execution script
Version: 1.0.0
Last modified: 02-03-2026
"""
import os, sys
import time
import pandas as pd
from typing import Dict, List, Optional, Any, Callable
import numpy as np
import multiprocessing

# =============================================================================
# System Configuration
# =============================================================================
CPU_COUNT = multiprocessing.cpu_count()
N_JOBS = max(1, CPU_COUNT - 1)  # Multi-process parallel count, keep 1 core for system
try:
    with open(".env", "r", encoding="utf-8") as _f:
        _env_overrides = _f.read()
except Exception:
    _env_overrides = None

def _ensure_references_on_path():
    script_dir = os.path.dirname(__file__)
    cur = script_dir
    for _ in range(8):
        candidate = os.path.join(cur, 'references')
        if os.path.isdir(candidate):
            # add parent folder (which contains `references`) to sys.path
            sys.path.insert(0, cur)
            return
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    # fallback: add a reasonable repo-root guess
    sys.path.insert(0, os.path.abspath(os.path.join(script_dir, '..', '..', '..')))


_ensure_references_on_path()

from references.func import get_dataset, missing_check, org_analysis
from references.analysis import (drop_abnormal_ym, drop_highmiss_features,
                               export_cleaning_report,
                               value_ratio_distribution_by_org)

# ==================== Path Configuration (Interactive Input) ====================
# Use 50-column test data as default, support interactive modification in command line
default_data_path = 'finance/loans_sample.csv'
default_output_dir = 'reports/credit-risk'

def _get_path_input(prompt, default):
    try:
        user_val = input(f"{prompt} (default: {default}): ").strip()
    except Exception:
        user_val = ''
    return user_val if user_val else default

DATA_PATH = _get_path_input('Please enter data file path DATA_PATH', default_data_path)
OUTPUT_DIR = _get_path_input('Please enter output directory OUTPUT_DIR', default_output_dir)
REPORT_PATH = os.path.join(OUTPUT_DIR, '数据清洗报告.xlsx')

# Data column name configuration (adjust according to actual data)
DATE_COL = _get_path_input('Please enter date column name in data', 'apply_date')
Y_COL = _get_path_input('Please enter label column name in data', 'target')
ORG_COL = _get_path_input('Please enter organization column name in data', 'org_info')

# Support multiple primary key column names input (comma or space separated)
def _get_list_input(prompt, default):
    try:
        user_val = input(f"{prompt} (default: {default}): ").strip()
    except Exception:
        user_val = ''
    if not user_val:
        user_val = default
    # Support comma or space separation
    parts = [p.strip() for p in user_val.replace(',', ' ').split() if p.strip()]
    return parts

KEY_COLS = _get_list_input('Please enter primary key column names in data (multiple columns separated by comma or space)', 'record_id')

# ==================== Multi-process Configuration Information ====================
print("=" * 60)
print("Multi-process Configuration")
print("=" * 60)
print(f"   Local CPU cores: {CPU_COUNT}")
print(f"   Current process count: {N_JOBS}")
print("=" * 60)

# ==================== OOS Organization Configuration (Interactive Input) ====================
# Default out-of-sample organization list, users can input custom list in comma-separated format during interaction
default_oos = [
   'orgA', 'orgB', 'orgC', 'orgD', 'orgE',
]

try:
    oos_input = input('Please enter out-of-sample organization list, comma separated (press Enter to use default list):').strip()
except Exception:
    oos_input = ''
if oos_input:
    OOS_ORGS = [s.strip() for s in oos_input.split(',') if s.strip()]
else:
    OOS_ORGS = default_oos

os.makedirs(OUTPUT_DIR, exist_ok=True)

# ==================== Interactive Hyperparameter Input ====================
def get_user_input(prompt, default, dtype=float):
    """Get user input, support default value and type conversion"""
    while True:
        try:
            user_input = input(f"{prompt} (default: {default}): ").strip()
            if not user_input:
                return default
            return dtype(user_input)
        except EOFError:
            return default
        except ValueError:
            print(f"   Invalid input, please enter {dtype.__name__} type")

# Record cleaning steps
steps = []

# Store parameters for each step
params = {}

# Timer decorator
def timer(step_name):
    """Timer decorator"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            print(f"\nStarting {step_name}...")
            start_time = time.time()
            result = func(*args, **kwargs)
            elapsed = time.time() - start_time
            print(f"   {step_name} elapsed: {elapsed:.2f} seconds")
            return result
        return wrapper
    return decorator

# ==================== Step 1: Get Data ====================
print("\n" + "=" * 60)
print("Step 1: Get Data")
print("=" * 60)
step_start = time.time()
# Use configuration from global_parameters
data = get_dataset(
    data_pth=DATA_PATH,
    date_colName=DATE_COL,
    y_colName=Y_COL,
    org_colName=ORG_COL,
    data_encode='utf-8',
    key_colNames=KEY_COLS,
    drop_colNames=[],
    miss_vals=[-1, -999, -1111]
)
print(f"   Original data: {data.shape}")
print(f"   Abnormal values replaced with NaN: [-1, -999, -1111]")
print(f"   Step 1 elapsed: {time.time() - step_start:.2f} seconds")

# ==================== Step 2: Organization Sample Analysis ====================
print("\n" + "=" * 60)
print("Step 2: Organization Sample Analysis")
print("=" * 60)
step_start = time.time()
org_stat = org_analysis(data, oos_orgs=OOS_ORGS)
steps.append(('机构样本统计', org_stat))
print(f"   Organization count: {data['new_org'].nunique()}, Month count: {data['new_date_ym'].nunique()}")
print(f"   Out-of-sample organizations: {len(OOS_ORGS)}")
print(f"   Step 2 elapsed: {time.time() - step_start:.2f} seconds")

# ==================== Step 3: Separate OOS Data ====================
print("\n" + "=" * 60)
print("Step 3: Separate OOS Data")
print("=" * 60)
step_start = time.time()
oos_data = data[data['new_org'].isin(OOS_ORGS)]
data = data[~data['new_org'].isin(OOS_ORGS)]
print(f"   OOS samples: {oos_data.shape[0]} rows")
print(f"   Modeling samples: {data.shape[0]} rows")
print(f"   OOS organizations: {OOS_ORGS}")
print(f"   Step 3 elapsed: {time.time() - step_start:.2f} seconds")
# Create separation information DataFrame
oos_info = pd.DataFrame({'变量': ['OOS样本', '建模样本'], '数量': [oos_data.shape[0], data.shape[0]]})
steps.append(('分离OOS数据', oos_info))

# ==================== Step 4: Filter Abnormal Months (Modeling Data Only) ====================
print("\n" + "=" * 60)
print("Step 4: Filter Abnormal Months (Modeling Data Only)")
print("=" * 60)
print("   Press Enter to use default values")
print("=" * 60)
params['min_ym_bad_sample'] = int(get_user_input("Bad sample count threshold", 10, int))
params['min_ym_sample'] = int(get_user_input("Total sample count threshold", 500, int))
step_start = time.time()
data_filtered, abnormal_ym = drop_abnormal_ym(data.copy(), min_ym_bad_sample=params['min_ym_bad_sample'], min_ym_sample=params['min_ym_sample'])
steps.append(('Step4-异常月份处理', abnormal_ym))
print(f"   After filtering: {data_filtered.shape}")
print(f"   Parameters: min_ym_bad_sample={params['min_ym_bad_sample']}, min_ym_sample={params['min_ym_sample']}")
if len(abnormal_ym) > 0:
    print(f"   Dropped months: {abnormal_ym['年月'].tolist()}")
    print(f"   Removal conditions: {abnormal_ym['去除条件'].tolist()}")
print(f"   Step 4 elapsed: {time.time() - step_start:.2f} seconds")

# ==================== Step 5: Calculate Missing Rate ====================
print("\n" + "=" * 60)
print("Step 5: Calculate Missing Rate")
print("=" * 60)
step_start = time.time()
orgs = data['new_org'].unique().tolist()
channel = {'整体': orgs}
miss_detail, miss_channel = missing_check(data, channel=channel)
# miss_detail: Missing rate details (format: feature, overall, org1, org2, ..., orgn)
# miss_channel: Overall missing rate
steps.append(('缺失率明细', miss_detail))
print(f"   Feature count: {len(miss_detail['变量'].unique())}")
print(f"   Organization count: {len(miss_detail.columns) - 2}")  # Subtract '变量' and '整体' columns
print(f"   Step 5 elapsed: {time.time() - step_start:.2f} seconds")

# ==================== Step 6: Drop High Missing Rate Features ====================
print("\n" + "=" * 60)
print("Step 6: Drop High Missing Rate Features")
print("=" * 60)
print("   Press Enter to use default values")
print("=" * 60)
params['missing_ratio'] = get_user_input("Missing rate threshold", 0.6)
step_start = time.time()
data_miss, dropped_miss = drop_highmiss_features(data.copy(), miss_channel, threshold=params['missing_ratio'])
steps.append(('Step6-高缺失率处理', dropped_miss))
print(f"   Dropped: {len(dropped_miss)}")
print(f"   Threshold: {params['missing_ratio']}")
if len(dropped_miss) > 0:
    print(f"   Dropped features: {dropped_miss['变量'].tolist()[:5]}...")
    print(f"   Removal conditions: {dropped_miss['去除条件'].tolist()[:5]}...")
print(f"   Step 6 elapsed: {time.time() - step_start:.2f} seconds")

# ==================== Step 11: Export Report ====================
print("\n" + "=" * 60)
print("Step 11: Export Report")
print("=" * 60)
step_start = time.time()

# Calculate value ratio distribution statistics (use all features)
print("   Calculating value ratio distribution statistics...")
features_for_value_ratio = [c for c in data.columns if c.startswith('i_')]
value_ratio_distribution = value_ratio_distribution_by_org(data, features_for_value_ratio, oos_orgs=OOS_ORGS)
print(f"   Value ratio distribution statistics: {len(value_ratio_distribution)} records")

# Add details and distribution statistics to steps list
steps.append(('Step5-有值率分布统计', value_ratio_distribution))

export_cleaning_report(REPORT_PATH, steps,
                      params=params,
                      value_ratio_distribution=value_ratio_distribution)
print(f"   Report: {REPORT_PATH}")
print(f"   Step 11 elapsed: {time.time() - step_start:.2f} seconds")

# ==================== Summary ====================
print("\n" + "=" * 60)
print("Data Cleaning Completed!")
print("=" * 60)
print(f"   Original data: {data.shape[0]} rows")
print(f"   Original features: {len([c for c in data.columns if c.startswith('i_')])}")
print(f"   Cleaning steps (each step executed independently, data not deleted):")
for name, df in steps:
    print(f"     - {name}: Dropped {df.shape[0] if hasattr(df, 'shape') else len(df)}")