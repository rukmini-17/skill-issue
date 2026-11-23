"""Variable selection and analysis module - simplified version
PSI calculation is reused in func.py, analysis.py only handles variable selection
"""
import pandas as pd
import numpy as np
from typing import List, Dict, Tuple
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from datetime import datetime


def drop_abnormal_ym(data: pd.DataFrame, min_ym_bad_sample: int = 1, 
                     min_ym_sample: int = 500) -> tuple:
    """Filter abnormal months - overall statistics, not by organization"""
    stat = data.groupby('new_date_ym').agg(
        bad_cnt=('new_target', 'sum'),
        total=('new_target', 'count')
    ).reset_index()
    
    abnormal = stat[(stat['bad_cnt'] < min_ym_bad_sample) | (stat['total'] < min_ym_sample)]
    abnormal = abnormal.rename(columns={'new_date_ym': '年月'})
    abnormal['去除条件'] = abnormal.apply(
        lambda x: f'bad sample count {x["bad_cnt"]} less than {min_ym_bad_sample}' if x['bad_cnt'] < min_ym_bad_sample else f'total sample count {x["total"]} less than {min_ym_sample}', axis=1
    )
    
    if len(abnormal) > 0:
        data = data[~data['new_date_ym'].isin(abnormal['年月'])]
    
    # Remove empty rows
    abnormal = abnormal.dropna(how='all')
    abnormal = abnormal.reset_index(drop=True)
    
    return data, abnormal


def drop_highmiss_features(data: pd.DataFrame, miss_channel: pd.DataFrame, 
                           threshold: float = 0.6) -> tuple:
    """Drop high missing rate features"""
    high_miss = miss_channel[miss_channel['整体缺失率'] > threshold].copy()
    high_miss['缺失率'] = high_miss['整体缺失率']
    
    # Modify removal condition to show specific missing rate value
    high_miss['去除条件'] = high_miss.apply(
        lambda x: f'overall missing rate is {x["缺失率"]:.4f}, exceeds threshold {threshold}', axis=1
    )
    
    # Remove empty rows
    high_miss = high_miss.dropna(how='all')
    high_miss = high_miss.reset_index(drop=True)
    
    # Drop high missing rate features
    if len(high_miss) > 0 and '变量' in high_miss.columns:
        to_drop = high_miss['变量'].tolist()
        data = data.drop(columns=[c for c in to_drop if c in data.columns])
    
    return data, high_miss[['变量', '缺失率', '去除条件']]

def value_ratio_distribution_by_org(data: pd.DataFrame, features: List[str], 
                                     oos_orgs: list = None, 
                                     value_bins: list = [0, 0.15, 0.35, 0.65, 0.95, 1.0]) -> pd.DataFrame:
    """Count number and proportion of features in different value ratio ranges for each organization
    
    Args:
        data: Data (containing new_org column)
        features: Feature list
        oos_orgs: Out-of-sample organization list
        value_bins: Value ratio range boundaries [0, 0.15, 0.35, 0.65, 0.95, 1.0]
    
    Returns:
        Value ratio distribution statistics table
    """
    if oos_orgs is None:
        oos_orgs = []
    
    # Define range labels
    bin_labels = ['[0, 15%)', '[15%, 35%)', '[35%, 65%)', '[65%, 95%)', '[95%, 100%]']
    
    result = []
    
    # Get all organizations
    orgs = data['new_org'].unique()
    
    for org in orgs:
        org_data = data[data['new_org'] == org]
        
        # Determine organization type
        org_type = '贷外' if org in oos_orgs else '建模'
        
        # Calculate value ratio for each feature (proportion of non-NaN)
        value_ratios = {}
        for f in features:
            if f in org_data.columns:
                non_null_count = org_data[f].notna().sum()
                total_count = len(org_data)
                value_ratios[f] = non_null_count / total_count if total_count > 0 else 0
        
        # Count number of features in each range
        total_vars = len(value_ratios)
        for i in range(len(value_bins) - 1):
            lower = value_bins[i]
            upper = value_bins[i + 1]
            if upper == 1.0:
                count = sum(1 for v in value_ratios.values() if lower <= v <= upper)
            else:
                count = sum(1 for v in value_ratios.values() if lower <= v < upper)
            ratio = count / total_vars if total_vars > 0 else 0
            result.append({
                '机构': org,
                '类型': org_type,
                '有值率区间': bin_labels[i],
                '变量个数': count,
                '占比': f'{ratio:.2%}'
            })
    
    return pd.DataFrame(result)

def export_cleaning_report(filepath: str, steps: list, 
                           iv_detail: pd.DataFrame = None,
                           iv_process: pd.DataFrame = None,
                           psi_detail: pd.DataFrame = None,
                           psi_process: pd.DataFrame = None,
                           params: dict = None,
                           iv_distribution: pd.DataFrame = None,
                           psi_distribution: pd.DataFrame = None,
                           value_ratio_distribution: pd.DataFrame = None):
    """Export cleaning report to xlsx - one sheet per step
    
    Args:
        filepath: Output path
        steps: Cleaning step list [(step name, DataFrame), ...]
        iv_detail: IV details (IV value of each feature in each organization and overall)
        iv_process: IV processing table (features that do not meet the conditions)
        psi_detail: PSI details (PSI value of each feature in each organization each month)
        psi_process: PSI processing table (features that do not meet the conditions)
        params: Hyperparameter dictionary, used to dynamically generate conditions
        iv_distribution: IV distribution statistics table
        psi_distribution: PSI distribution statistics table
        value_ratio_distribution: Value ratio distribution statistics table
    """
    from openpyxl import load_workbook
    
    try:
        wb = load_workbook(filepath)
    except Exception:
        wb = Workbook()
        wb.remove(wb.active)
    
    # Summary sheet - only show real filtering steps
    if '汇总' in wb.sheetnames:
        del wb['汇总']
    ws = wb.create_sheet('汇总', 0)
    ws['A1'] = 'Data Cleaning Report'
    ws['A2'] = f'Generated at: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'
    ws['A4'] = 'Step'
    ws['B4'] = 'Operation Details'
    ws['C4'] = 'Operation Result'
    ws['D4'] = 'Condition'
    
    # Only show real filtering steps (excluding details and distribution statistics)
    filter_steps = [
        'Step4-异常月份处理', 'Step6-高缺失率处理', 'Step7-IV处理', 
        'Step8-PSI处理', 'Step9-null importance处理', 'Step10-高相关性剔除'
    ]
    
    # Steps to exclude (details and distribution statistics)
    exclude_steps = [
        'Step7-IV明细', 'Step7-IV分布统计', 'Step8-PSI明细', 
        'Step8-PSI分布统计', 'Step5-有值率分布统计'
    ]
    
    # Steps that need to show drop count
    show_drop_count_steps = ['分离OOS数据']
    
    # Steps that only show parameter standards (no operation result)
    show_param_only_steps = ['机构样本统计', '缺失率明细']
    
    # Add note: each step is executed independently
    ws['A3'] = 'Note: Each filtering step is executed independently, data is not deleted, only statistics of features that do not meet conditions are recorded'
    
    # Get parameters, use default values if not provided
    if params is None:
        params = {}
    
    min_ym_bad_sample = params.get('min_ym_bad_sample', 10)
    min_ym_sample = params.get('min_ym_sample', 500)
    missing_ratio = params.get('missing_ratio', 0.6)
    overall_iv_threshold = params.get('overall_iv_threshold', 0.1)
    org_iv_threshold = params.get('org_iv_threshold', 0.1)
    max_org_threshold = params.get('max_org_threshold', 2)
    psi_threshold = params.get('psi_threshold', 0.1)
    max_months_ratio = params.get('max_months_ratio', 1/3)
    max_orgs = params.get('max_orgs', 4)
    gain_threshold = params.get('gain_threshold', 50)
    
    step_num = 1
    for name, df in steps:
        # Skip detail and distribution statistics steps
        if name in exclude_steps:
            continue
        
        # Remove StepX- prefix from operation details
        display_name = name.replace('Step4-', '').replace('Step6-', '').replace('Step7-', '').replace('Step8-', '').replace('Step9-', '').replace('Step10-', '')
        
        # Only show parameter standard steps (no operation result)
        if name in show_param_only_steps:
            ws.cell(4+step_num, 1, step_num)
            ws.cell(4+step_num, 2, display_name)
            result = ''
            # Condition: show parameter standards
            if name == '机构样本统计':
                condition = 'Statistics of sample count and bad sample rate for each organization'
            elif name == '缺失率明细':
                condition = 'Calculate missing rate for each feature'
            else:
                condition = ''
            ws.cell(4+step_num, 3, result)
            ws.cell(4+step_num, 4, condition)
            step_num += 1
        # Show steps that need to display drop count
        elif name in show_drop_count_steps:
            ws.cell(4+step_num, 1, step_num)
            ws.cell(4+step_num, 2, display_name)
            if df is not None and len(df) > 0:
                if name == '分离OOS数据':
                    # Special handling: show OOS and modeling sample counts
                    if '变量' in df.columns and '数量' in df.columns:
                    
                        oos_count = df[df['变量'] == 'OOS样本']['数量'].values[0] if len(df[df['变量'] == 'OOS样本']) > 0 else 0
                        model_count = df[df['变量'] == '建模样本']['数量'].values[0] if len(df[df['变量'] == '建模样本']) > 0 else 0
                        result = f'OOS samples {oos_count}, modeling samples {model_count}'
                    else:
                        result = f'{len(df)} rows'
                elif '变量' in df.columns:
                    result = f'Dropped {len(df)} features'
                else:
                    result = f'Dropped {len(df)}'
                condition = ''
            else:
                result = 'Empty'
                condition = ''
            ws.cell(4+step_num, 3, result)
            ws.cell(4+step_num, 4, condition)
            step_num += 1
        elif name in filter_steps:
            ws.cell(4+step_num, 1, step_num)
            ws.cell(4+step_num, 2, display_name)
            
            # Generate operation result and condition
            if df is not None and len(df) > 0:
                if name == 'Step4-异常月份处理':
                    # Operation result: dropped months
                    if '年月' in df.columns:
                        result = 'Dropped ' + ','.join(df['年月'].astype(str).tolist())
                    else:
                        result = 'Dropped ' + ','.join(df.iloc[:, 0].astype(str).tolist())
                    # Condition: parameter standards
                    condition = f'Months with bad sample count less than {min_ym_bad_sample} or total sample count less than {min_ym_sample} will be dropped (independent execution)'
                elif name == 'Step6-高缺失率处理':
                    # Operation result: number of dropped features
                    if '变量' in df.columns:
                        result = f'Dropped {len(df)} features'
                    else:
                        result = f'Dropped {len(df)}'
                    # Condition: parameter standards
                    condition = f'Features with overall missing rate greater than {missing_ratio} will be dropped (independent execution)'
                elif name == 'Step7-IV处理':
                    # Operation result: number of dropped features
                    if '变量' in df.columns:
                        result = f'Dropped {len(df)} features'
                    else:
                        result = f'Dropped {len(df)}'
                    # Condition: parameter standards
                    condition = f'Features with overall IV less than {overall_iv_threshold} or IV less than {org_iv_threshold} in {max_org_threshold} or more organizations will be dropped (independent execution)'
                elif name == 'Step8-PSI处理':
                    # Operation result: number of dropped features
                    if '变量' in df.columns:
                        result = f'Dropped {len(df)} features'
                    else:
                        result = f'Dropped {len(df)}'
                    # Condition: parameter standards
                    condition = f'PSI threshold {psi_threshold}, if an organization has more than {max_months_ratio:.0%} months with PSI greater than {psi_threshold}, the organization is considered unstable, if more than {max_orgs} organizations are unstable, the feature will be dropped (independent execution)'
                elif name == 'Step9-null importance处理':
                    # Operation result: number of dropped features
                    if '变量' in df.columns:
                        result = f'Dropped {len(df[df["状态"]=="去除"])} features'
                    else:
                        result = f'Dropped {len(df)}'
                    # Condition: parameter standards
                    condition = f'Features with absolute difference of gain values before and after permutation less than {gain_threshold} will be identified as noise and dropped (independent execution)'
                elif name == 'Step10-高相关性剔除':
                    # Operation result: number of dropped features
                    if '变量' in df.columns:
                        result = f'Dropped {len(df)} features'
                    else:
                        result = f'Dropped {len(df)}'
                    # Condition: parameter standards
                    max_corr = params.get('max_corr', 0.9)
                    top_n_keep = params.get('top_n_keep', 20)
                    condition = f'Features with correlation greater than {max_corr} will be dropped, keep top {top_n_keep} features by original gain ranking (independent execution)'
                else:
                    result = 'Dropped ' + str(len(df))
                    condition = ''
            else:
                result = 'Empty'
                condition = ''
            
            ws.cell(4+step_num, 3, result)
            ws.cell(4+step_num, 4, condition)
            step_num += 1
    
    # Calculate total number of dropped features (take union of dropped features from each step)
    all_dropped_vars = set()
    for name, df in steps:
        if name in filter_steps and df is not None and len(df) > 0 and '变量' in df.columns:
            if name == 'Step9-null importance处理':
                # null importance processing needs to filter features with status "去除"
                dropped_vars = df[df['状态'] == '去除']['变量'].tolist()
            else:
                dropped_vars = df['变量'].tolist()
            # Take union (deduplicated)
            all_dropped_vars = all_dropped_vars.union(set(dropped_vars))
    
    # Add final statistics row
    final_step_num = step_num
    ws.cell(4+final_step_num, 1, final_step_num)
    ws.cell(4+final_step_num, 2, 'Final Dropped Features Statistics')
    ws.cell(4+final_step_num, 3, f'Total dropped {len(all_dropped_vars)} features (union of dropped features from each step)')
    ws.cell(4+final_step_num, 4, 'Each step is executed independently, final dropped features are the union of dropped features from each step')
    
    # Details of each step (create sheets in step progression order)
    # Define sheet creation order
    sheet_order = [
        '机构样本统计', '分离OOS数据', 'Step4-异常月份处理', '缺失率明细',
        'Step5-有值率分布统计', 'Step6-高缺失率处理', 'Step7-IV明细', 'Step7-IV处理',
        'Step7-IV分布统计', 'Step8-PSI明细', 'Step8-PSI处理', 'Step8-PSI分布统计',
        'Step9-null importance处理', 'Step10-高相关性剔除'
    ]
    
    # Create sheets in order
    for sheet_name in sheet_order:
        # Find corresponding DataFrame in steps
        df = None
        for name, step_df in steps:
            if name == sheet_name:
                df = step_df
                break
        
        if df is not None:
            if sheet_name in wb.sheetnames:
                del wb[sheet_name]
            ws_detail = wb.create_sheet(sheet_name)
            
            for j, col in enumerate(df.columns):
                ws_detail.cell(1, j+1, col)
            
            for i, row in df.iterrows():
                for j, val in enumerate(row):
                    # Write value directly, avoid character escaping issues
                    ws_detail.cell(i+2, j+1, val if val is not None else '')
            
            header_fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
            header_font = Font(color="FFFFFF", bold=True)
            for cell in ws_detail[1]:
                cell.fill = header_fill
                cell.font = header_font
    
    wb.save(filepath)