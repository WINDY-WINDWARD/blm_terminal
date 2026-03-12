BLM Analytics API Documentation
Base URL: http://127.0.0.1:4455
Generated: /mnt/drive3/500GB/p1/Projects/blm_terminal/backend/docs/api_responses.py

============================================================
  GET /health
============================================================
Status: 200
{
  "status": "ok"
}

============================================================
  GET /api/stockuniverse
============================================================
Status: 200
Response: List of 2254 items
Sample item (first):
{
  "symbol": "20MICRONS",
  "companyName": "20 Microns Limited",
  "segment": "EQUITY",
  "industry": "Industrial Minerals",
  "sectorPE": 8.86,
  "symbolPE": 8.91,
  "industryInfo": {
    "macro": "Commodities",
    "sector": "Metals & Mining",
    "industry": "Minerals & Mining",
    "basicIndustry": "Industrial Minerals"
  },
  "lastUpdateTime": "2026-03-10T14:31:25",
  "screenerTradesId": null
}

============================================================
  GET /api/stockuniverse/{symbol}
============================================================
Status: 200
{
  "symbol": "RELIANCE",
  "companyName": "Reliance Industries Limited",
  "segment": "EQUITY",
  "industry": "Refineries & Marketing",
  "sectorPE": 19.78,
  "symbolPE": 19.78,
  "industryInfo": {
    "macro": "Energy",
    "sector": "Oil Gas & Consumable Fuels",
    "industry": "Petroleum Products",
    "basicIndustry": "Refineries & Marketing"
  },
  "lastUpdateTime": "2026-03-10T16:00:00",
  "screenerTradesId": "2726"
}

============================================================
  GET /api/stockuniverse/search/{prefix}
============================================================
Status: 200
Response: List of 11 items
Sample item (first):
{
  "symbol": "RCOM",
  "companyName": "Reliance Communications Limited",
  "segment": "EQUITY",
  "industry": "Telecom - Cellular & Fixed line services",
  "sectorPE": null,
  "symbolPE": null,
  "industryInfo": {
    "macro": "Telecommunication",
    "sector": "Telecommunication",
    "industry": "Telecom - Services",
    "basicIndustry": "Telecom - Cellular & Fixed line services"
  },
  "lastUpdateTime": "2026-03-10T16:00:00",
  "screenerTradesId": null
}

============================================================
  GET /api/watchlist
============================================================
Status: 200
Response: List of 20 items
Sample item (first):
{
  "id": 1,
  "symbol": "IDFCFIRSTB",
  "exchange": "NSE",
  "created_at": "2026-03-09T19:16:45.049000"
}


============================================================
  GET /api/corporatefilings/{symbol}
============================================================
Status: 200
Response: CSV text (4145 chars)

Full CSV content (first 5000 chars):
```
"QUARTER ENDED"|"31-DEC-2024"|"30-SEP-2024"|"30-JUN-2024"|"31-MAR-2024"|"31-DEC-2023"
"PARTICULARS"|"UNAUDITED"|"UNAUDITED"|"UNAUDITED"|"AUDITED"|"UNAUDITED"
"Part 1"|""|""|""|""|""
"Revenue from operations"|""|""|""|""|""
"Revenue from operations"|"12826000"|"13405400"|"13433100"|"15101400"|"13057900"
"Other income"|"321400"|"380100"|"350200"|"349700"|"296900"
"Total income"|"13147400"|"13785500"|"13783300"|"15451100"|"13354800"
"Expenses"|""|""|""|""|""
"(a) Cost of materials consumed"|"9156100"|"9683600"|"9967900"|"9625900"|"9402100"
"(b) Purchases of stock-in-trade"|"390400"|"338300"|"396700"|"334700"|"378900"
"(c) Changes in inventories of finished goods, work-in-progress and stock-in-trade"|"237100"|"266200"|"296300"|"361300"|"298200"
"(d) Employee benefits expense"|"218100"|"207700"|"215600"|"194600"|"186200"
"(e) Finance costs"|"237100"|"266200"|"296300"|"361300"|"298200"
"(f) Depreciation and amortisation expense"|"445900"|"435000"|"470800"|"485600"|"456700"
"(g) Other expenses"|"1948600"|"1905600"|"1909000"|"2085500"|"1662900"
"Total Expenses"|"11987700"|"12764100"|"12768700"|"13946000"|"12057000"
"Profit / (Loss) before exceptional items and tax"|"-"|"-"|"-"|"-"|"-"
"Exceptional items"|"0"|"0"|"0"|"0"|"0"
"Profit / (Loss) before tax"|"1159700"|"1021400"|"1014600"|"1505100"|"1297800"
"Tax Expenses"|""|""|""|""|""
"Current Tax"|"248300"|"211300"|"245700"|"321200"|"248700"
"Deferred Tax"|"39300"|"38800"|"7800"|"55600"|"56700"
"Total Tax expense"|"287600"|"250100"|"253500"|"376800"|"305400"
"Net movement in regulatory deferral account balances related to profit or loss and the related deferred tax movement"|"-"|"-"|"-"|"-"|"-"
"Profit (Loss) for the period from continuing operations"|"872100"|"771300"|"761100"|"1128300"|"992400"
"Profit / (loss) from discontinued operations"|"0"|"0"|"0"|"0"|"0"
"Tax expense of discontinued operations"|"0"|"0"|"0"|"0"|"0"
"Profit / (loss) from Discontinued operations (after tax)"|"0"|"0"|"0"|"0"|"0"
"Profit / (loss) for the period"|"-"|"-"|"-"|"-"|"-"
"Share of profit / (loss) of associates"|"0"|"0"|"0"|"0"|"0"
"Consolidated Net Profit / Loss for the period"|"872100"|"771300"|"761100"|"1128300"|"992400"
"Other comprehensive income"|"-"|"-"|"-"|"-"|"-"
"Total comprehensive income"|"-"|"-"|"-"|"-"|"-"
"Total profit or loss, attributable to"|""|""|""|""|""
"Profit or loss, attributable to owners of parent"|"-"|"-"|"-"|"-"|"-"
"Total profit or loss, attributable to non-controlling interests"|"-"|"-"|"-"|"-"|"-"
"Total Comprehensive income for the period attributable to"|""|""|""|""|""
"Comprehensive income for the period attributable to owners of parent"|"-"|"-"|"-"|"-"|"-"
"Total comprehensive income for the period attributable to owners of parent non-controlling interests"|"-"|"-"|"-"|"-"|"-"
"Details of equity share capital"|""|""|""|""|""
"Paid-up equity share capital"|"1353200"|"676600"|"676600"|"676600"|"676600"
"Face Value(in Rs.)"|"10"|"10"|"10"|"10"|"10"
"Details of debt securities"|""|""|""|""|""
"Paid-up debt capital"|"-"|"-"|"-"|"-"|"-"
"Face value of debt securities (in Rs.)"|"-"|"-"|"-"|"-"|"-"
"Reserve excluding Revaluation Reserves as per balance sheet of previous accounting year"|"-"|"-"|"-"|"-"|"-"
"Debenture redemption reserve"|"-"|"-"|"-"|"-"|"-"
"Earnings per share"|""|""|""|""|""
"Earnings per equity share for continuing operations"|""|""|""|""|""
"Basic EPS for continuing operations"|"-"|"-"|"-"|"-"|"-"
"Diluted EPS for continuing operations"|"-"|"-"|"-"|"-"|"-"
"Earnings per equity share for discontinued operations"|""|""|""|""|""
"Basic EPS for continued and discontinued operations"|"-"|"-"|"-"|"-"|"-"
"Diluted EPS for discontinued operations"|"-"|"-"|"-"|"-"|"-"
"Earnings per equity share"|""|""|""|""|""
"Basic EPS for continued and discontinued operations"|"6.44"|"11.4"|"11.25"|"16.68"|"14.67"
"Diluted EPS for continued and discontinued operations"|"6.44"|"11.4"|"11.25"|"16.68"|"14.67"
"Debt equity ratio (in %)"|"-"|"-"|"-"|"-"|"-"
"Debt service coverage ratio (in %)"|"-"|"-"|"-"|"-"|"-"
"Interest service coverage ratio (in %)"|"-"|"-"|"-"|"-"|"-"

```

============================================================
  GET /api/market/top-gainers
============================================================
Status: 200
Response: List of 5 items
Sample item (first):
{
  "symbol": "JSWENERGY",
  "identifier": "",
  "series": "EQ",
  "open": "484",
  "dayHigh": "528",
  "dayLow": "484",
  "lastPrice": "519",
  "previousClose": "488",
  "change": 31.0,
  "pChange": 6.35,
  "totalTradedVolume": 19316979,
  "totalTradedValue": 10017978479.19,
  "yearHigh": "579",
  "yearLow": "427.75",
  "nearWKH": 10.362694300518134,
  "nearWKL": -21.332554061952074,
  "perChange365d": 0.6,
  "perChange30d": 7.15,
  "date365dAgo": "12-Mar-2025",
  "date30dAgo": "10-Feb-2026",
  "chartTodayPath": "https://nsearchives.nseindia.com/today/JSWENERGYEQN.svg",
  "chart30dPath": "https://nsearchives.nseindia.com/30d/JSWENERGY-EQ.svg",
  "chart365dPath": "https://nsearchives.nseindia.com/365d/JSWENERGY-EQ.svg",
  "meta": {
    "symbol": "JSWENERGY",
    "companyName": "JSW Energy Limited",
    "industry": "Power Generation",
    "activeSeries": [
      "EQ"
    ],
    "debtSeries": [],
    "isFNOSec": true,
    "isCASec": false,
    "isSLBSec": true,
    "isDebtSec": false,
    "isSuspended": false,
    "tempSuspendedSeries": [
      "BE"
    ],
    "isETFSec": false,
    "isDelisted": false,
    "isin": "INE121E01018",
    "slb_isin": "INE121E01018",
    "listingDate": "2010-01-04",
    "isMunicipalBond": false,
    "isHybridSymbol": false,
    "segment": "EQUITY",
    "quotepreopenstatus": {
      "equityTime": "12-Mar-2026 16:00:00",
      "preOpenTime": "12-Mar-2026 09:07:07",
      "QuotePreOpenFlag": false
    }
  }
}

============================================================
  GET /api/market/top-losers
============================================================
Status: 200
Response: List of 5 items
Sample item (first):
{
  "symbol": "PPLPHARMA",
  "identifier": "",
  "series": "EQ",
  "open": "155.2",
  "dayHigh": "155.2",
  "dayLow": "144.96",
  "lastPrice": "145.5",
  "previousClose": "155.42",
  "change": -9.92,
  "pChange": -6.38,
  "totalTradedVolume": 8629241,
  "totalTradedValue": 1273589679.19,
  "yearHigh": "240.95",
  "yearLow": "144.96",
  "nearWKH": 39.61402780659888,
  "nearWKL": -0.3725165562913852,
  "perChange365d": -27.89,
  "perChange30d": -10.94,
  "date365dAgo": "12-Mar-2025",
  "date30dAgo": "10-Feb-2026",
  "chartTodayPath": "https://nsearchives.nseindia.com/today/PPLPHARMAEQN.svg",
  "chart30dPath": "https://nsearchives.nseindia.com/30d/PPLPHARMA-EQ.svg",
  "chart365dPath": "https://nsearchives.nseindia.com/365d/PPLPHARMA-EQ.svg",
  "meta": {
    "symbol": "PPLPHARMA",
    "companyName": "Piramal Pharma Limited",
    "industry": "Pharmaceuticals",
    "activeSeries": [
      "EQ"
    ],
    "debtSeries": [],
    "isFNOSec": true,
    "isCASec": false,
    "isSLBSec": true,
    "isDebtSec": false,
    "isSuspended": false,
    "tempSuspendedSeries": [],
    "isETFSec": false,
    "isDelisted": false,
    "isin": "INE0DK501011",
    "slb_isin": "INE0DK501011",
    "listingDate": "2022-10-19",
    "isMunicipalBond": false,
    "isHybridSymbol": false,
    "segment": "EQUITY",
    "quotepreopenstatus": {
      "equityTime": "12-Mar-2026 16:00:00",
      "preOpenTime": "12-Mar-2026 09:07:07",
      "QuotePreOpenFlag": false
    }
  }
}

============================================================
  GET /api/market/bulk-deals/{symbol}
============================================================
Status: 200
Response: List of 0 items

============================================================
  GET /api/market/block-deals/{symbol}
============================================================
Status: 200
Response: List of 0 items

============================================================
  GET /api/market/high-short-interest
============================================================
Status: 200
Response: List of 71 items
Sample item (first):
{
  "date": "11-Mar-2026",
  "symbol": "AARTIIND",
  "name": "AARTI INDUSTRIES LTD",
  "clientName": null,
  "buySell": null,
  "qty": "50",
  "watp": null,
  "remarks": null
}

============================================================
  GET /api/market/change-ranges/{symbol}
============================================================
Status: 200
{
  "oneDayPercent": -11.78,
  "oneWeekPercent": 0.04,
  "oneMonthPercent": -4.07,
  "threeMonthPercent": -10.7,
  "sixMonthPercent": -0.36,
  "oneYearPercent": 10.58,
  "twoYearPercent": -5.79,
  "threeYearPercent": 19.69,
  "fiveYearPercent": 30.05
}

============================================================
  GET /api/market/symbol-data/{symbol}
============================================================
Status: 200
{
  "equityResponse": [
    {
      "orderBook": {
        "buyPrice1": 0,
        "buyQuantity1": 0,
        "buyPrice2": 0,
        "buyQuantity2": 0,
        "buyPrice3": 0,
        "buyQuantity3": 0,
        "buyPrice4": 0,
        "buyQuantity4": 0,
        "buyPrice5": 0,
        "buyQuantity5": 0,
        "sellPrice1": 0,
        "sellQuantity1": 0,
        "sellPrice2": 0,
        "sellQuantity2": 0,
        "sellPrice3": 0,
        "sellQuantity3": 0,
        "sellPrice4": 0,
        "sellQuantity4": 0,
        "sellPrice5": 0,
        "sellQuantity5": 0,
        "lastPrice": 1390,
        "totalBuyQuantity": 0,
        "totalSellQuantity": 0,
        "perBuyQty": 0,
        "perSellQty": 0
      },
      "metaData": {
        "identifier": "RELIANCEEQN",
        "companyName": "Reliance Industries Limited",
        "isinCode": "INE002A01018",
        "symbol": "RELIANCE",
        "series": "EQ",
        "marketType": "N",
        "open": 1390,
        "dayHigh": 1410.9,
        "dayLow": 1381.1,
        "previousClose": 1390.2,
        "averagePrice": 1397.56,
        "change": -0.2,
        "pChange": -0.01,
        "basePrice": 1390.2,
        "closePrice": 1392.2,
        "indicativeClose": 0,
        "ic_change": 0,
        "ic_pchange": 0,
        "spoChange": 0,
        "spoPchange": 0,
        "symbolStatus": "NM",
        "adjPrice": 0,
        "iep": 0,
        "ieq": 0
      },
      "tradeInfo": {
        "totalTradedVolume": 20939959,
        "totalTradedValue": 29264849100.04,
        "series": "EQ",
        "lastPrice": 1390,
        "issuedSize": 13532472634,
        "basePrice": 1390.2,
        "ffmc": 9359115316033.64,
        "faceValue": 10,
        "impactCost": 0.01,
        "deliveryToTradedQuantity": 42.85,
        "applicableMargin": 12.5,
        "marketLot": null,
        "quantitytraded": 20939959,
        "deliveryquantity": 8971814,
        "totalMarketCap": 18810136961260,
        "secwisedelposdate": "12-Mar-2026 00:00:00"
      },
      "priceInfo": {
        "yearHightDt": "05-Jan-2026 00:00:00",
        "yearLowDt": "07-Apr-2025 00:00:00",
        "yearHigh": 1611.8,
        "yearLow": 1114.85,
        "priceBand": "1253.00-1531.40",
        "cmDailyVolatility": "1.31",
        "cmAnnualVolatility": "25.03",
        "tickSize": 0.1,
        "inav": 0,
        "isINav": "False",
        "ppriceBand": "No Band"
      },
      "secInfo": {
        "secStatus": "Listed",
        "listingDate": "29-Nov-1995 00:00:00",
        "pdSectorInd": "NIFTY 500                                         ",
        "pdSectorPe": "19.31",
        "pdSymbolPe": "19.31",
        "isSuspended": "Active",
        "basicIndustry": "Refineries & Marketing",
        "index": "Nifty 50",
        "deliveryQuantity": "8971814",
        "deliveryTotradedQuantity": "42.85",
        "securityvar": "8.2",
        "indexvar": "0",
        "extremelossMargin": "3.5",
        "varMargin": "9",
        "adhocMargin": "0",
        "applicableMargin": "12.5",
        "bondType": null,
        "issueDesc": null,
        "issueDate": null,
        "maturityDate": null,
        "couponRate": null,
        "nxtIpDate": null,
        "creditRating": null,
        "macro": "Energy",
        "sector": "Oil Gas & Consumable Fuels",
        "industryInfo": "Petroleum Products",
        "indexList": [
          "NIFTY 50",
          "NIFTY 100",
          "NIFTY 200",
          "NIFTY 500",
          "NIFTY ALPHA LOW-VOLATILITY 30",
          "NIFTY ALPHA QUALITY VALUE LOW-VOLATILITY 30",
          "NIFTY COMMODITIES",
          "NIFTY CONGLOMERATE 50",
          "NIFTY ENERGY",
          "NIFTY EV & NEW AGE AUTOMOTIVE",
          "NIFTY INDIA FPI 150",
          "NIFTY INDIA MANUFACTURING",
          "NIFTY INDIA SELECT 5 CORPORATE GROUPS (MAATR)",
          "NIFTY INFRASTRUCTURE",
          "NIFTY LARGEMIDCAP 250",
          "NIFTY LOW VOLATILITY 50",
          "NIFTY MOBILITY",
          "NIFTY OIL & GAS",
          "NIFTY TOP 10 EQUAL WEIGHT",
          "NIFTY TOP 15 EQUAL WEIGHT",
          "NIFTY TOP 20 EQUAL WEIGHT",
          "NIFTY TOTAL MARKET",
          "NIFTY100 ENHANCED ESG",
          "NIFTY100 EQUAL WEIGHT",
          "NIFTY100 ESG",
          "NIFTY100 ESG SECTOR LEADERS",
          "NIFTY100 LIQUID 15",
          "NIFTY100 LOW VOLATILITY 30",
          "NIFTY50 EQUAL WEIGHT",
          "NIFTY500 EQUAL WEIGHT",
          "NIFTY500 LARGEMIDSMALL EQUAL-CAP WEIGHTED",
          "NIFTY500 MULTICAP 50:25:25",
          "NIFTY500 MULTICAP INDIA MANUFACTURING 50:30:20",
          "NIFTY500 MULTICAP INFRASTRUCTURE 50:30:20"
        ],
        "boardStatus": "Main",
        "tradingSegment": "Normal Market",
        "sessionNo": null,
        "classShare": "Equity",
        "nameOfComplianceOfficer": null,
        "sddcompliance": null
      },
      "lastUpdateTime": "12-Mar-2026 16:00:00"
    }
  ]
}

============================================================
  GET /api/market/52week-low
============================================================
Status: 200
Top-level keys: ['data', 'low', 'timestamp']
data: List of 323 items
Sample item (first):
{
  "symbol": "ABREL",
  "series": "EQ",
  "comapnyName": "Aditya Birla Real Estate Limited",
  "new52WHL": 1141.6,
  "prev52WHL": 1170.1,
  "prevHLDate": "10-Mar-2026",
  "ltp": 1199.9,
  "prevClose": "1183",
  "change": 16.9,
  "pChange": 1.4285714285714286
}

============================================================
  GET /api/market/52week-high
============================================================
Status: 200
Top-level keys: ['high', 'data', 'timestamp']
data: List of 31 items
Sample item (first):
{
  "symbol": "ABB",
  "series": "EQ",
  "comapnyName": "ABB India Limited",
  "new52WHL": 6429.5,
  "prev52WHL": 6325,
  "prevHLDate": "11-Mar-2026",
  "ltp": 6415.5,
  "prevClose": "6280",
  "change": 135.5,
  "pChange": 2.1576433121019107
}

============================================================
  GET /api/market/volume-gainers
============================================================
Status: 200
Top-level keys: ['data', 'timestamp']
data: List of 25 items
Sample item (first):
{
  "symbol": "MOQUALITY",
  "companyName": "Motilal Oswal Mutual Fund - Motilal Oswal S&P BSE Quality ETF",
  "volume": 206273,
  "week1AvgVolume": 34888,
  "week1volChange": 5.912377585630344,
  "week2AvgVolume": 21488,
  "week2volChange": 9.599450856291885,
  "ltp": 188.92,
  "pChange": -0.38,
  "turnover": 389.54656
}

============================================================
  GET /api/screener/search
============================================================
Status: 200
Response: List of 9 items
Sample item (first):
{
  "id": 2726,
  "name": "Reliance Industries Ltd",
  "url": "/company/RELIANCE/consolidated/"
}

============================================================
  GET /api/screener/company/{symbol}
============================================================
Status: 200
{
  "symbol": "RELIANCE",
  "name": "Reliance Industries Ltd",
  "screener_warehouse_id": "6598251",
  "ratios": {
    "market_cap": "18,82,771 Cr.",
    "price": "1,392",
    "pe": "24.5",
    "book_value": "648",
    "dividend_yield": "0.40%",
    "roce": "9.69%",
    "roe": "8.40 %",
    "face_value": "10.0",
    "high_52w": "1,612",
    "low_52w": "1,115",
    "eps_growth_5years": "9.92%",
    "dividend_payout": "10.7%",
    "piotroski_score": "4.00",
    "promoter_holding": "50.0%",
    "roic": "10.6%",
    "total_assets": "20,38,946Cr.",
    "ebit": "1,42,777Cr.",
    "working_capital": "46,670Cr.",
    "sales": "10,24,548Cr.",
    "return_on_equity": "8.40%",
    "debt_to_equity": "0.43",
    "sales_growth": "9.01%",
    "profit_growth": "10.9%",
    "sales_growth_5years": "10.0%",
    "profit_var_5yrs": "9.93%",
    "change_in_prom_hold": "0.00%",
    "opm": "17.4%",
    "profit_after_tax": "76,747Cr.",
    "mar_cap": "18,82,771Cr.",
    "sales_qtr": "2,64,905Cr.",
    "price_to_earning": "24.5",
    "price_to_book_value": "2.15",
    "industry_pe": "9.96",
    "current_price": "1,392",
    "price_to_sales": "1.84",
    "enterprise_value": "21,45,864Cr.",
    "current_ratio": "1.10",
    "peg_ratio": "4.57",
    "pat_qtr": "18,645Cr.",
    "qtr_sales_var": "10.4%",
    "qtr_profit_var": "0.57%",
    "earnings_yield": "6.65%",
    "pledged_percentage": "0.00%",
    "debt": "3,74,593Cr.",
    "eps": "61.5",
    "cmp_/_fcf": "124",
    "evebitda": "10.8",
    "int_coverage": "5.36",
    "sales_growth_3years": "11.5%",
    "profit_var_3yrs": "5.37%",
    "sales_last_year": "9,62,820Cr.",
    "op_ann": "1,65,598Cr.",
    "ebidt_last_year": "1,82,019Cr.",
    "dep_ann": "53,136Cr.",
    "ebit_last_year": "1,28,883Cr.",
    "pbt_ann": "1,06,017Cr.",
    "interest_last_year": "24,269Cr.",
    "tax_last_year": "25,230Cr.",
    "pat_ann": "68,732Cr.",
    "rsi": "45.4",
    "macd": "-12.3",
    "market_cap_to_sales": "1.84",
    "debt_to_profit": "4.61",
    "graham": "947",
    "altman_z_score": "2.84",
    "roe_3yr": "8.79%",
    "chg_in_fii_hold": "0.44%",
    "chg_in_dii_hold": "-0.15%"
  },
  "quarters": [
    {
      "period": "Dec 2025",
      "sales": "264,905",
      "net_profit": "22,290",
      "eps": "13.78"
    },
    {
      "period": "Sep 2025",
      "sales": "254,623",
      "net_profit": "22,092",
      "eps": "13.42"
    },
    {
      "period": "Jun 2025",
      "sales": "243,632",
      "net_profit": "30,783",
      "eps": "19.95"
    },
    {
      "period": "Mar 2025",
      "sales": "261,388",
      "net_profit": "22,611",
      "eps": "14.34"
    }
  ]
}

============================================================
  GET /api/screener/trades/{symbol}
============================================================
Status: 200
warehouse_id: 2726
insider_trades: 308 records
Sample record (first):
{
  "period": "Sep 2025",
  "person": "Shobha Agarwal",
  "category": "Immediate Relative",
  "quantity_raw": "-1,25,000",
  "quantity": -125000,
  "direction": "down",
  "avg_price_raw": "1,385",
  "avg_price": 1385,
  "value_raw": "1,731",
  "value": 1731,
  "value_in": "lacs",
  "small_quantity": true
}
bulk_deals: 25 records
Sample record (first):
{
  "period": "27 Mar 2020",
  "person": "Tattvam Enterprises Llp",
  "category": "",
  "quantity_raw": "B",
  "quantity": null,
  "direction": null,
  "avg_price_raw": "7,67,35,388",
  "avg_price": 76735388,
  "value_raw": "1,056",
  "value": 1056,
  "value_in": "price",
  "small_quantity": false
}
block_deals: 297 records
Sample record (first):
{
  "period": "27 Jan 2026",
  "person": "Morgan Stanley Asia (Singapore) Pte.",
  "category": "",
  "quantity_raw": "Sale",
  "quantity": null,
  "direction": null,
  "avg_price_raw": "11,51,736",
  "avg_price": 1151736,
  "value_raw": "1,384",
  "value": 1384,
  "value_in": "price",
  "small_quantity": false
}

============================================================
  GET /api/screener/quarterly/{symbol}
============================================================
Status: 200
symbol: RELIANCE
consolidated: True
quarterly_results: 4 year(s)
Sample year (2022):
{
  "Dec": {
    "Sales": "216,737",
    "Expenses": "181,728",
    "Operating Profit": "35,009",
    "OPM %": "16%",
    "Other Income": "3,377",
    "Interest": "5,201",
    "Depreciation": "10,183",
    "Profit before tax": "23,002",
    "Tax %": "23%",
    "Net Profit": "17,806",
    "EPS in Rs": "11.67",
    "Raw PDF": null
  }
}

============================================================
  GET /api/ai/health
============================================================
Status: 200
{
  "status": "unconfigured",
  "model": null
}

============================================================
  POST /api/ai/summarize
============================================================
Using data from: GET /api/corporatefilings/RELIANCE
Status: 503
Response: Model still loading (503 Service Unavailable)
{
  "_error": "Upstream error",
  "_status": 503
}

============================================================
  END OF DOCUMENTATION
============================================================