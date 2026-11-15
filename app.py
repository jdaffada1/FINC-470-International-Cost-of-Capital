"""FINC 470 International Cost of Capital — Streamlit Community Cloud entry point."""
from __future__ import annotations
import io
import re
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup
from calculations import calculate, verify

BASE = Path(__file__).parent
BETA_URL = 'https://pages.stern.nyu.edu/~adamodar/pc/datasets/betas.xls'
SPREAD_URL = 'https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/ratings.htm'
OECD_URL = 'https://www.oecd.org/en/publications/corporate-tax-statistics-2026_73af6222-en/full-report/statutory-corporate-income-tax-rates_ce84abb9.html'
TE_URL = 'https://tradingeconomics.com/bonds'
HEADERS = {'User-Agent':'Mozilla/5.0 (compatible; FINC470EducationalApp/1.0)'}

st.set_page_config(page_title='Global Cost of Capital | FINC 470', page_icon='🌐', layout='wide')
st.markdown('''<style>
.block-container{padding-top:1.5rem;max-width:1350px}
[data-testid="stMetric"]{border:1px solid #34465a;border-radius:14px;padding:15px;background:rgba(65,85,110,.08)}
.small-note{opacity:.78;font-size:.86rem}
</style>''', unsafe_allow_html=True)

@st.cache_data(show_spinner=False)
def snapshot_data():
    betas = pd.read_csv(BASE/'data/industry_betas.csv')
    market = pd.read_csv(BASE/'data/market_snapshots.csv')
    spread = pd.read_csv(BASE/'data/bbb_spread.csv')
    return betas, market, spread


def download(url):
    r = requests.get(url, headers=HEADERS, timeout=18)
    r.raise_for_status()
    return r.content


def refresh_betas():
    """Read Damodaran's actual 'Industry Averages' worksheet, not the FAQ sheet."""
    payload = io.BytesIO(download(BETA_URL))
    workbook = pd.ExcelFile(payload)
    sheets = sorted(workbook.sheet_names, key=lambda name: 0 if 'industry average' in name.lower() else 1)
    for sheet in sheets:
        raw = pd.read_excel(workbook, sheet_name=sheet, header=None)
        for i in range(min(75, len(raw))):
            headers = [re.sub(r'\s+', ' ', str(v)).strip().lower() for v in raw.iloc[i].tolist()]
            industry_idx = next((j for j, h in enumerate(headers) if h in ('industry name', 'industry')), None)
            beta_idx = next((j for j, h in enumerate(headers) if h == 'unlevered beta'), None)
            if industry_idx is None or beta_idx is None:
                continue
            data = raw.iloc[i + 1:, [industry_idx, beta_idx]].copy()
            data.columns = ['industry', 'unlevered_beta']
            data['industry'] = data['industry'].astype('string').str.strip()
            data['unlevered_beta'] = pd.to_numeric(data['unlevered_beta'], errors='coerce')
            data = data.dropna(subset=['industry', 'unlevered_beta'])
            data = data[data['industry'].str.len().gt(0)]
            data = data[data['unlevered_beta'].between(0, 10)]
            data = data.drop_duplicates('industry')
            if len(data) >= 50:
                return data.reset_index(drop=True)
    raise ValueError('No valid Industry Averages table found in Damodaran workbook.')


def refresh_spread():
    soup = BeautifulSoup(download(SPREAD_URL), 'html.parser')
    for tr in soup.find_all('tr'):
        cells = [c.get_text(' ', strip=True) for c in tr.find_all(['td','th'])]
        for j, cell in enumerate(cells):
            if re.search(r'Baa2\s*/\s*BBB',cell,re.I):
                # The first occurrence is the large non-financial firms table.
                for following in cells[j+1:j+3]:
                    m = re.search(r'(\d+(?:\.\d+)?)\s*%', following)
                    if m: return float(m.group(1))
    raise ValueError('Baa2/BBB spread not found in Damodaran table.')


def _clean_country(s):
    s = re.sub(r'\s+', ' ', str(s)).strip()
    s = re.sub(r'\s*\[.*?\]', '', s)
    return s


def _valid_yield(value):
    try:
        number = float(str(value).replace('%', '').replace(',', '').strip())
        return number if -5.0 < number < 100.0 else None
    except (ValueError, TypeError):
        return None


def _country_slug(country):
    # Trading Economics uses this route for country government bond yield pages.
    return country.lower().replace(' ', '-')


def _read_te_bond_page(country):
    """Try a public country 10Y page, verifying that the 10Y quote is identifiable."""
    url = f'https://tradingeconomics.com/{_country_slug(country)}/government-bond-yield'
    soup = BeautifulSoup(download(url), 'html.parser')
    # Structured metadata, when provided, is preferable to generic numeric matches.
    for tag in soup.find_all('meta'):
        if tag.get('property') in ('og:description', 'description') or tag.get('name') == 'description':
            content = tag.get('content', '')
            if '10-year' in content.lower() or '10 year' in content.lower():
                match = re.search(r'(?:was|at|to|yield(?:ed)?|is)\s+(?:at\s+)?(-?\d+(?:\.\d+)?)\s*%', content, re.I)
                if match:
                    value = _valid_yield(match.group(1))
                    if value is not None:
                        return value
    # A labeled bond table row is also reliable; reject 2Y, 5Y, TIPS, etc.
    for tr in soup.find_all('tr'):
        cells = tr.find_all(['td', 'th'])
        if len(cells) < 2:
            continue
        name = cells[0].get_text(' ', strip=True)
        if re.fullmatch(r'(?:US|UK|[A-Za-z .-]+)\s+10Y', name, re.I):
            value = _valid_yield(cells[1].get_text(' ', strip=True))
            if value is not None:
                return value
    raise ValueError(f'No independently identifiable 10Y yield on {country} public page')


def refresh_bond_yields():
    """Prefer authenticated TE 10Y API; try public country pages as a fallback.

    No API key is required to use the app. An optional Trading Economics key
    can be supplied through Streamlit secrets as TE_API_KEY (never commit it).
    """
    countries = list(snapshot_data()[1]['country'].astype(str))
    try:
        key = st.secrets.get('TE_API_KEY', '')
    except Exception:
        key = ''
    if key:
        response = requests.get('https://api.tradingeconomics.com/markets/bond',
                                params={'c': key, 'type': '10Y', 'f': 'json'},
                                headers=HEADERS, timeout=20)
        response.raise_for_status()
        records = response.json()
        if not isinstance(records, list):
            raise ValueError('Trading Economics API did not return bond records')
        result = {}
        for record in records:
            if not isinstance(record, dict):
                continue
            name = str(record.get('Country', '')).strip()
            label = str(record.get('Name', ''))
            if name in countries and re.search(r'\b10Y\b|10.year', label, re.I):
                value = _valid_yield(record.get('Last'))
                if value is not None:
                    result[name] = value
        if 'United States' in result and len(result) >= 3:
            return result
        raise ValueError('Trading Economics API returned insufficient valid 10Y quotes')

    # Public pages may deny automated access. Refresh individual verified quotes;
    # never silently substitute a different maturity or a forecast.
    result = {}
    for country in countries:
        try:
            result[country] = _read_te_bond_page(country)
        except (requests.RequestException, ValueError):
            continue
    if 'United States' not in result or len(result) < 3:
        raise ValueError('Trading Economics public pages blocked or did not expose verifiable 10Y quotes; import a verified CSV or use dated snapshots.')
    return result


def refresh_oecd_taxes():
    # OECD's narrative page is not a stable country-by-country machine-readable feed.
    # Only accept a clearly identified table with combined statutory rates.
    tables = pd.read_html(io.BytesIO(download(OECD_URL)))
    out={}
    countries=set(snapshot_data()[1]['country'])
    for table in tables:
        if isinstance(table.columns,pd.MultiIndex): table.columns=[' '.join(map(str,c)) for c in table.columns]
        country_cols=[c for c in table.columns if 'jurisdiction' in str(c).lower() or 'country' in str(c).lower()]
        rate_cols=[c for c in table.columns if 'combined' in str(c).lower() and ('rate' in str(c).lower() or 'statutory' in str(c).lower())]
        if not country_cols or not rate_cols: continue
        for _,row in table.iterrows():
            name=_clean_country(row[country_cols[0]])
            if name in countries:
                try:
                    x=float(str(row[rate_cols[0]]).replace('%','').strip())
                    if 0<=x<=70: out[name]=x
                except ValueError: pass
    if len(out)<3: raise ValueError('OECD page has no reliably parseable combined-rate table; use 2026 lecture snapshot or manual input.')
    return out


betas, market, spreads = snapshot_data()
if 'refreshed' not in st.session_state: st.session_state.refreshed={}
if 'refresh_status' not in st.session_state: st.session_state.refresh_status={}

st.title('🌐 Global Cost of Capital')
st.caption('FINC 470 · USD vs. local-currency financing · Professor Rebelo lecture methodology')
with st.sidebar:
    st.header('Project assumptions')
    industry_options=sorted(betas['industry'].astype(str).tolist())
    default_industry=next((x for x in industry_options if 'Software (System' in x),industry_options[0])
    industry=st.selectbox('Industry',industry_options,index=industry_options.index(default_industry))
    countries=market['country'].tolist()
    country=st.selectbox('Target country',countries,index=countries.index('United States'))
    erp_pct=st.number_input('Equity risk premium (%)',min_value=0.0,max_value=100.0,value=6.5,step=.25,format='%.2f')
    debt_pct=st.slider('Target debt share (%)',0.0,99.0,30.0,1.0)
    tax_choice=st.radio('Tax rate used in both currencies',['U.S.','Selected country'],horizontal=True)
    st.divider()
    st.subheader('Source refresh')
    if st.button('🔄 Refresh all public sources',use_container_width=True):
        with st.spinner('Checking Damodaran, Trading Economics and OECD…'):
            for key,fn in [('betas',refresh_betas),('spread',refresh_spread),('yields',refresh_bond_yields),('taxes',refresh_oecd_taxes)]:
                if 'supplied by user' in st.session_state.refresh_status.get(key, ''):
                    continue
                try:
                    val=fn();st.session_state.refreshed[key]=val
                    st.session_state.refresh_status[key]=f'Updated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}'
                except Exception as exc:
                    st.session_state.refresh_status[key]=f'Update unavailable: {str(exc)[:110]}'
        st.rerun()
    st.caption('Refresh is best-effort: source websites can block scraping or change their tables. Dated snapshots remain available; failures are never labeled live.')
    with st.expander('Import verified Trading Economics 10Y yields (CSV fallback)'):
        st.caption('Download or transcribe observed 10-year government yields from Trading Economics. CSV columns: country,yield_pct. Use actual yields in percent, not forecasts, and record the observation date. Import is session-scoped.')
        uploaded_yields = st.file_uploader('Trading Economics 10Y yield CSV', type=['csv'], key='te_yields_upload')
        yield_date = st.text_input('10Y yield observation date', placeholder='YYYY-MM-DD', key='te_yields_date')
        if st.button('Apply verified 10Y yields', disabled=uploaded_yields is None):
            try:
                datetime.strptime(yield_date.strip(), '%Y-%m-%d')
                table = pd.read_csv(uploaded_yields)
                if not {'country', 'yield_pct'}.issubset(table.columns):
                    raise ValueError('CSV needs columns country,yield_pct')
                allowed = set(market['country'].astype(str))
                values = {}
                for _, item in table.iterrows():
                    name = str(item['country']).strip()
                    value = _valid_yield(item['yield_pct'])
                    if name in allowed and value is not None:
                        values[name] = value
                if 'United States' not in values or len(values) < 2:
                    raise ValueError('Include a valid United States 10Y yield and at least one other supported country.')
                st.session_state.refreshed['yields'] = values
                st.session_state.refresh_status['yields'] = (f'Verified Trading Economics CSV supplied by user · observation {yield_date.strip()} · '
                    f'imported {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")} · {len(values)} countries')
                st.rerun()
            except Exception as exc:
                st.error(f'Could not import 10Y yields: {exc}')
    with st.expander('Import verified OECD tax rates (optional)'):
        st.caption('If OECD blocks automated access, download its official country-level combined statutory tax rates as CSV. Columns: country, tax_pct. Rates must be percentages (e.g. 25.5), not decimals. Include the official source date below.')
        uploaded_taxes = st.file_uploader('OECD tax-rate CSV', type=['csv'], key='oecd_upload')
        source_date = st.text_input('OECD source publication / observation date', placeholder='YYYY-MM-DD', key='oecd_source_date')
        if st.button('Apply verified OECD CSV', disabled=uploaded_taxes is None):
            try:
                if not source_date.strip():
                    raise ValueError('Enter the OECD source date first.')
                datetime.strptime(source_date.strip(), '%Y-%m-%d')
                tax_file = pd.read_csv(uploaded_taxes)
                if not {'country', 'tax_pct'}.issubset(tax_file.columns):
                    raise ValueError('CSV needs country and tax_pct columns.')
                tax_file['tax_pct'] = pd.to_numeric(tax_file['tax_pct'], errors='raise')
                if tax_file['country'].duplicated().any() or not tax_file['tax_pct'].between(0,70).all():
                    raise ValueError('Duplicate countries or invalid percentage rates.')
                allowed = set(market['country'].astype(str))
                selected = {str(r.country): float(r.tax_pct) for r in tax_file.itertuples(index=False) if str(r.country) in allowed}
                if not selected:
                    raise ValueError('No countries matched the app country names.')
                st.session_state.refreshed['taxes'] = selected
                st.session_state.refresh_status['taxes'] = f'Official OECD CSV supplied by user · observation {source_date.strip()} · imported {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}'
                st.rerun()
            except Exception as exc:
                st.error(f'Could not import OECD rates: {exc}')


if 'betas' in st.session_state.refreshed:
    betas_live=st.session_state.refreshed['betas']
else: betas_live=betas
if industry not in set(betas_live['industry']):
    st.warning('Selected industry missing from refreshed source; using original snapshot for this industry.')
    beta_default=float(betas.loc[betas.industry==industry,'unlevered_beta'].iloc[0])
else:
    beta_default=float(betas_live.loc[betas_live.industry==industry,'unlevered_beta'].iloc[0])
row=market.loc[market.country==country].iloc[0]
us=market.loc[market.country=='United States'].iloc[0]
yield_updates=st.session_state.refreshed.get('yields',{})
tax_updates=st.session_state.refreshed.get('taxes',{})
us_yield=float(yield_updates.get('United States',us.yield_pct))
fx_yield=float(yield_updates.get(country,row.yield_pct))
us_tax=float(tax_updates.get('United States',us.tax_pct))
fx_tax=float(tax_updates.get(country,row.tax_pct)) if pd.notna(row.tax_pct) or country in tax_updates else None
spread=float(st.session_state.refreshed.get('spread',spreads.iloc[0].spread_pct))

st.subheader('Market data and overrides')
st.caption('Check the source labels below. Manual values are assumptions, not live quotes.')
with st.expander('Edit retrieved inputs / manually override',expanded=True):
    a,b,c=st.columns(3)
    with a:
        beta_override=st.checkbox('Override unlevered beta',key='ob')
        beta=a.number_input('Unlevered beta',min_value=0.0,max_value=10.0,value=beta_default,format='%.6f',disabled=not beta_override,key=f'beta_{industry}_{beta_default:.6f}' if not beta_override else 'beta_manual')
        us_override=st.checkbox('Override U.S. 10Y yield',key='ous')
        rf_us=a.number_input('U.S. 10Y yield (%)',min_value=-10.0,max_value=100.0,value=us_yield,format='%.4f',disabled=not us_override,key=f'us_yield_{us_yield:.4f}' if not us_override else 'us_yield_manual')
    with b:
        fx_override=st.checkbox('Override selected-country 10Y yield',key='ofx')
        rf_fx=b.number_input(f'{country} 10Y yield (%)',min_value=-10.0,max_value=100.0,value=fx_yield,format='%.4f',disabled=not fx_override,key=f'fx_yield_{country}_{fx_yield:.4f}' if not fx_override else 'fx_yield_manual')
        spread_override=st.checkbox('Override USD BBB spread',key='os')
        usd_spread=b.number_input('USD BBB spread (percentage points)',min_value=0.0,max_value=100.0,value=spread,format='%.4f',disabled=not spread_override,key=f'spread_{spread:.4f}' if not spread_override else 'spread_manual')
    with c:
        selected_tax=us_tax if tax_choice=='U.S.' else (fx_tax if fx_tax is not None else us_tax)
        tax_override=st.checkbox('Override selected corporate tax rate',key='ot')
        tax=c.number_input('Corporate tax rate (%)',min_value=0.0,max_value=100.0,value=float(selected_tax),format='%.4f',disabled=not tax_override,key=f'tax_{tax_choice}_{country}_{selected_tax:.4f}' if not tax_override else 'tax_manual')
        foreign_spread_override=st.checkbox('Override FOREIGN-currency BBB spread',key='ofs')
        auto_foreign_spread=usd_spread*(1+rf_fx/100)/(1+rf_us/100)
        fx_spread=c.number_input('Foreign BBB spread (percentage points)',min_value=0.0,max_value=100.0,value=float(auto_foreign_spread),format='%.4f',disabled=not foreign_spread_override,key=f'foreign_spread_{country}_{auto_foreign_spread:.4f}' if not foreign_spread_override else 'foreign_spread_manual')

if tax_choice=='Selected country' and fx_tax is None and not tax_override:
    st.error(f'No verified OECD tax rate available for {country}. Enable the corporate tax override and enter a verified rate to calculate.')
    st.stop()

try:
    p=dict(beta_u=float(beta),debt_share=debt_pct/100,tax=tax/100,erp=erp_pct/100,
           rf_us=rf_us/100,rf_foreign=rf_fx/100,spread_us=usd_spread/100,
           foreign_spread_override=fx_spread/100 if foreign_spread_override else None)
    r=calculate(**p)
except ValueError as exc:
    st.error(str(exc));st.stop()

st.divider()
st.subheader(f'Cost of capital · USD vs. {row.currency}')
c1,c2=st.columns(2)
with c1:
    st.markdown('#### 🇺🇸 USD financing')
    st.metric('Cost of equity',f'{r.usd_equity*100:.4f}%')
    st.metric('Pretax cost of debt',f'{r.usd_debt*100:.4f}%')
    st.metric('WACC',f'{r.usd_wacc*100:.4f}%')
with c2:
    st.markdown(f'#### {country} · {row.currency} financing')
    st.metric('Cost of equity',f'{r.foreign_equity*100:.4f}%')
    st.metric('Pretax cost of debt',f'{r.foreign_debt*100:.4f}%')
    st.metric('WACC',f'{r.foreign_wacc*100:.4f}%')

comparison=pd.DataFrame({
    'Metric':['Unlevered beta','Levered equity beta','Cost of equity (%)','Pretax debt cost (%)','After-tax debt cost (%)','WACC (%)'],
    'USD':[r.beta_unlevered,r.beta_equity,r.usd_equity*100,r.usd_debt*100,r.usd_debt_after_tax*100,r.usd_wacc*100],
    row.currency:[r.beta_unlevered,r.beta_equity,r.foreign_equity*100,r.foreign_debt*100,r.foreign_debt_after_tax*100,r.foreign_wacc*100]
})
st.dataframe(comparison.style.format({'USD':'{:.4f}',row.currency:'{:.4f}'}),hide_index=True,use_container_width=True)
st.caption(f'Levered beta = {r.beta_equity:.6f} · D/E = {r.debt_to_equity:.6f} · Yield conversion factor = {r.factor:.8f} · Foreign BBB spread = {r.foreign_spread*100:.4f} pp')

with st.expander('Methodology and financial assumptions'):
    st.latex(r'\frac{D}{E}=\frac{d}{1-d},\quad \beta_E=\beta_U\left[1+(1-\tau)\frac{D}{E}\right]')
    st.latex(r'R_e=R_f+\beta_E\,ERP,\quad R_d=R_f+s')
    st.latex(r'WACC=(1-d)R_e+dR_d(1-\tau)')
    st.latex(r'1+R_e^*=(1+R_e)\frac{1+R_f^*}{1+R_f}')
    st.latex(r's^*=s\frac{1+R_f^*}{1+R_f},\quad R_d^*=R_f^*+s^*')
    st.latex(r'WACC^*=(1-d)R_e^*+dR_d^*(1-\tau)')
    st.write('Government bond yields are risk-free proxies, not default-free rates. Industry beta is a U.S. proxy; there is no separate country equity premium. Debt beta is assumed zero, tax shields fully usable, and target leverage constant. Foreign conversion assumes equal real rates and relative purchasing-power parity.')

st.subheader('All-industry comparison')
records=[]
for _,item in betas_live.iterrows():
    try:
        x=calculate(**{**p,'beta_u':float(item.unlevered_beta)})
        records.append({'Industry':item.industry,'Unlevered beta':x.beta_unlevered,'Levered beta':x.beta_equity,'USD equity %':x.usd_equity*100,'USD WACC %':x.usd_wacc*100,f'{row.currency} equity %':x.foreign_equity*100,f'{row.currency} WACC %':x.foreign_wacc*100})
    except (ValueError,TypeError):pass
all_industries=pd.DataFrame(records).sort_values('Industry')
st.dataframe(all_industries,use_container_width=True,hide_index=True)
st.download_button('⬇️ Download all-industry results (CSV)',all_industries.to_csv(index=False).encode(),'all_industry_cost_of_capital.csv','text/csv')

st.subheader('Data provenance')
status=st.session_state.refresh_status
source_rows=[
    ('Industry beta',BETA_URL,'Damodaran file dated 2026-01-05 (snapshot)' if 'betas' not in st.session_state.refreshed else status.get('betas','refreshed')),
    ('BBB spread',SPREAD_URL,'Damodaran Jan 2026 (snapshot)' if 'spread' not in st.session_state.refreshed else status.get('spread','refreshed')),
    ('Corporate tax',OECD_URL,'OECD 2026 lecture table (snapshot)' if 'taxes' not in st.session_state.refreshed else status.get('taxes','refreshed')),
    ('10Y government yields',TE_URL,'Lecture snapshot dated 2026-11-06' if 'yields' not in st.session_state.refreshed else status.get('yields','refreshed')),
]
for name,url,source in source_rows:
    st.markdown(f'**{name}:** [{url}]({url}) — {source}')
for name,msg in status.items():
    if msg.startswith('Update unavailable'):st.warning(f'{name}: {msg}')
if any([beta_override,us_override,fx_override,spread_override,tax_override,foreign_spread_override]):
    st.info('Manual overrides are active. Review input values before using these results.')

st.subheader('Verification')
checks=verify()
for label,ok in checks.items():
    st.write(('✅' if ok else '❌')+' '+label)
st.caption('Colombia lecture benchmark uses separate illustrative inputs (βu=0.8, d=30%, tax=35%, ERP=6.5%, US 4%, COP 12%, USD spread 1.5%). Tests run independently of dashboard selections.')
