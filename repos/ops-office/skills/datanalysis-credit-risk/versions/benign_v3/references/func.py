"""Data processing functions module"""
import pandas as pd
import numpy as np
from typing import List, Dict, Tuple
from datetime import datetime

try:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    HAS_OPENPYXL = True
except:
    HAS_OPENPYXL = False


def get_dataset(data_pth: str, date_colName: str, y_colName: str, 
                org_colName: str, data_encode: str, key_colNames: List[str],
                drop_colNames: List[str] = None,
                miss_vals: List[int] = None) -> pd.DataFrame:
    """Load and format data
    
    Args:
        data_pth: Data file path
        date_colName: Date column name
        y_colName: Label column name
        org_colName: Organization column name
        data_encode: Data encoding
        key_colNames: Primary key columns (for deduplication)
        drop_colNames: Columns to drop
        miss_vals: List of abnormal values to replace with NaN, default [-1, -999, -1111]
    """
    if drop_colNames is None:
        drop_colNames = []
    if miss_vals is None:
        miss_vals = [-1, -999, -1111]
    
    # Multi-format reading
    for fmt, reader in [('parquet', pd.read_parquet), ('csv', pd.read_csv), 
                         ('xlsx', pd.read_excel), ('pkl', pd.read_pickle)]:
        try:
            data = reader(data_pth)
            break
        except Exception:
            continue
    
    # Replace abnormal values with NaN
    data.replace({v: np.nan for v in miss_vals}, inplace=True)
    
    # Deduplication and filtering
    data = data[data[y_colName].isin([0, 1])]
    data = data.drop_duplicates(subset=key_colNames)
    
    # Drop invalid columns
    data.drop(columns=[c for c in drop_colNames if c in data.columns], errors='ignore')
    data.drop(columns=[c for c in data.columns if data[c].nunique() <= 1], errors='ignore')
    
    # Rename columns
    data.rename(columns={date_colName: 'new_date', y_colName: 'new_target', 
                         org_colName: 'new_org'}, inplace=True)
    data['new_date'] = data['new_date'].astype(str).str.replace('-', '', regex=False).str[:8]
    data['new_date_ym'] = data['new_date'].str[:6]
    
    return data


def org_analysis(data: pd.DataFrame, oos_orgs: List[str] = None) -> pd.DataFrame:
    """Organization sample statistics analysis
    
    Args:
        data: Data
        oos_orgs: Out-of-sample organization list, used to identify OOS samples
    """
    stat = data.groupby(['new_org', 'new_date_ym']).agg(
        单月坏样本数=('new_target', 'sum'),
        单月总样本数=('new_target', 'count'),
        单月坏样率=('new_target', 'mean')
    ).reset_index()
    
    # Cumulative statistics
    stat['总坏样本数'] = stat.groupby('new_org')['单月坏样本数'].transform('sum')
    stat['总样本数'] = stat.groupby('new_org')['单月总样本数'].transform('sum')
    stat['总坏样率'] = stat['总坏样本数'] / stat['总样本数']
    
    # Mark whether it is an OOS organization
    if oos_orgs and len(oos_orgs) > 0:
        stat['样本类型'] = stat['new_org'].apply(lambda x: '贷外' if x in oos_orgs else '建模')
    else:
        stat['样本类型'] = '建模'
    
    stat = stat.rename(columns={'new_org': '机构', 'new_date_ym': '年月'})
    
    # Sort by sample type (modeling first, OOS last)
    stat = stat.sort_values(['样本类型', '机构', '年月'], ascending=[True, True, True])
    stat = stat.reset_index(drop=True)
    
    return stat[['机构', '年月', '单月坏样本数', '单月总样本数', '单月坏样率', '总坏样本数', '总样本数', '总坏样率', '样本类型']]


def missing_check(data: pd.DataFrame, channel: Dict[str, List[str]] = None) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Calculate missing rate - including overall and organization-level missing rates
    
    Returns:
        miss_detail: Missing rate details (format: variable, overall, org1, org2, ..., orgn)
        miss_ch: Overall missing rate (overall missing rate for each variable)
    """
    miss_vals = [-1, -999, -1111]
    miss_ch = []
    
    # Exclude non-variable columns: record_id, target, org_info, etc.
    exclude_cols = ['new_date', 'new_date_ym', 'new_target', 'new_org', 'record_id', 'target', 'org_info']
    cols = [c for c in data.columns if c not in exclude_cols]
    
    # Calculate overall missing rate
    for col in cols:
        rate = ((data[col].isin(miss_vals)) | (data[col].isna())).mean()
        miss_ch.append({'变量': col, '整体缺失率': round(rate, 4)})
    
    miss_ch = pd.DataFrame(miss_ch)
    
    # Calculate organization-level missing rates and convert to wide format
    orgs = sorted(data['new_org'].unique())
    miss_detail_dict = {'变量': []}
    miss_detail_dict['整体'] = []
    
    for org in orgs:
        miss_detail_dict[org] = []
    
    for col in cols:
        miss_detail_dict['变量'].append(col)
        # Overall missing rate
        overall_rate = ((data[col].isin(miss_vals)) | (data[col].isna())).mean()
        miss_detail_dict['整体'].append(round(overall_rate, 4))
        
        # Missing rate for each organization
        for org in orgs:
            org_data = data[data['new_org'] == org]
            rate = ((org_data[col].isin(miss_vals)) | (org_data[col].isna())).mean()
            miss_detail_dict[org].append(round(rate, 4))
    
    miss_detail = pd.DataFrame(miss_detail_dict)
    # Sort by overall missing rate in descending order
    miss_detail = miss_detail.sort_values('整体', ascending=False)
    miss_detail = miss_detail.reset_index(drop=True)
    
    return miss_detail, miss_ch


def calculate_corr(data: pd.DataFrame, features: List[str]) -> pd.DataFrame:
    """Calculate correlation matrix"""
    corr = data[features].corr().abs()
    return corr


def export_report_xlsx(filepath: str, data_name: str, data: pd.DataFrame, 
                       sheet_name: str, description: str = ""):
    """Export xlsx report - supports appending"""
    try:
        from openpyxl import load_workbook
        wb = load_workbook(filepath)
        ws = wb.create_sheet(sheet_name)
    except:
        wb = Workbook()
        ws = wb.active
        ws.title = sheet_name
    
    # Write description
    ws['A1'] = f"Data: {data_name}"
    ws['A2'] = f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    if description:
        ws['A3'] = f"Description: {description}"
    
    # Write data
    start_row = 5
    for i, col in enumerate(data.columns):
        ws.cell(start_row, i+1, col)
    
    for i, row in enumerate(data.values):
        for j, val in enumerate(row):
            ws.cell(start_row+1+i, j+1, val)
    
    # Styles
    header_fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True)
    for cell in ws[start_row]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal='center')
    
    wb.save(filepath)
    print(f"[{sheet_name}] Saved to {filepath}")