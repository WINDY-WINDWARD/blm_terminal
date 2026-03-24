BLM Analytics API Documentation
Base URL: http://127.0.0.1:4455
Generated: D:\500GB\p1\Projects\blm_terminal\backend\docs\api_responses.py

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
Response: List of 2278 items
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
  "screenerTradesId": null,
  "mcUrl": "https://www.moneycontrol.com/india/stockpricequote/miningminerals/20microns/2M",
  "reviewStatus": "fuzzy",
  "matchConfidence": 1.0,
  "mcMatchSource": "name",
  "mcCompanyName": "20 Microns",
  "morningstarId": null,
  "fairValue": null,
  "fairValueUpdatedAt": null
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
  "screenerTradesId": "2726",
  "mcUrl": "https://www.moneycontrol.com/india/stockpricequote/cement-major/rainindustries/RC12",
  "reviewStatus": "ambiguous",
  "matchConfidence": 0.8235294117647058,
  "mcMatchSource": "name",
  "mcCompanyName": "Rain Industries",
  "morningstarId": null,
  "fairValue": null,
  "fairValueUpdatedAt": null
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
  "screenerTradesId": null,
  "mcUrl": "https://www.moneycontrol.com/india/stockpricequote/telecommunications-service/reliancecommunications/RC13",
  "reviewStatus": "ambiguous",
  "matchConfidence": 0.7222222222222221,
  "mcMatchSource": "name",
  "mcCompanyName": "Reliance Comm",
  "morningstarId": null,
  "fairValue": null,
  "fairValueUpdatedAt": null
}

============================================================
  GET /api/watchlist
============================================================
Status: 200
Response: List of 21 items
Sample item (first):
{
  "id": 6,
  "watchlist_id": 1,
  "symbol": "IRFC",
  "exchange": "NSE",
  "created_at": "2026-03-10T12:36:24.478000"
}

============================================================
  POST /api/watchlist
============================================================
Status: 201
{
  "id": 25,
  "watchlist_id": 1,
  "symbol": "TCS",
  "exchange": "NSE",
  "created_at": "2026-03-14T17:11:30"
}

============================================================
  DELETE /api/watchlist/{id}
============================================================
Status: 200
{
  "ok": true
}

============================================================
  GET /api/watchlists
============================================================
Status: 200
Response: List of 2 items
Sample item (first):
{
  "id": 1,
  "name": "Default",
  "created_at": "2026-03-19T08:04:29",
  "item_count": 20
}

============================================================
  POST /api/watchlists
============================================================
Status: 422
"{\"detail\":[{\"type\":\"value_error\",\"loc\":[\"body\",\"name\"],\"msg\":\"Value error, must contain only letters and hyphens\",\"input\":\"Test Watchlist\",\"ctx\":{\"error\":{}}}]}"

============================================================
  GET /api/watchlists/{watchlist_id}/items
============================================================
Status: 200
Response: List of 20 items
Sample item (first):
{
  "id": 7,
  "watchlist_id": 1,
  "symbol": "WEBELSOLAR",
  "exchange": "NSE",
  "created_at": "2026-03-10T12:36:58.393000"
}

============================================================
  POST /api/watchlists/{watchlist_id}/items
============================================================
Status: 201
{
  "id": 54,
  "watchlist_id": 1,
  "symbol": "INFY",
  "exchange": "NSE",
  "created_at": "2026-03-24T19:18:44"
}

============================================================
  DELETE /api/watchlists/1/items/54
============================================================
Status: 200
{
  "ok": true
}

============================================================
  GET /api/notifications?watchlist_id=1
============================================================
Status: 200
Response: List of 0 items

============================================================
  DELETE /api/notifications?watchlist_id=1&all=true
============================================================
Status: 200
{
  "ok": true
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
  "symbol": "SAMMAANCAP",
  "identifier": "",
  "series": "EQ",
  "open": "135.9",
  "dayHigh": "139.72",
  "dayLow": "129.65",
  "lastPrice": "139.15",
  "previousClose": "130",
  "change": 9.15,
  "pChange": 7.04,
  "totalTradedVolume": 27486426,
  "totalTradedValue": 3738153936.0,
  "yearHigh": "192.95",
  "yearLow": "97.61",
  "nearWKH": 27.882871210158065,
  "nearWKL": -42.55711504968754,
  "perChange365d": 16.39,
  "perChange30d": -10.08,
  "date365dAgo": "24-Mar-2025",
  "date30dAgo": "20-Feb-2026",
  "chartTodayPath": "https://nsearchives.nseindia.com/today/SAMMAANCAPEQN.svg",
  "chart30dPath": "https://nsearchives.nseindia.com/30d/SAMMAANCAP-EQ.svg",
  "chart365dPath": "https://nsearchives.nseindia.com/365d/SAMMAANCAP-EQ.svg",
  "meta": {
    "symbol": "SAMMAANCAP",
    "companyName": "Sammaan Capital Limited",
    "industry": "Housing Finance Company",
    "activeSeries": [
      "EQ",
      "T0"
    ],
    "debtSeries": [],
    "isFNOSec": true,
    "isCASec": false,
    "isSLBSec": true,
    "isDebtSec": true,
    "isSuspended": false,
    "tempSuspendedSeries": [
      "BG",
      "BJ",
      "BK",
      "BN",
      "BP",
      "BY",
      "N1",
      "N2",
      "N3",
      "N4",
      "N5",
      "N6",
      "N7",
      "NG",
      "NH",
      "NI",
      "NJ",
      "NK",
      "NL",
      "NX",
      "NY",
      "NZ",
      "W1",
      "Y1",
      "Y2",
      "Y3",
      "YD",
      "YG",
      "YH",
      "YI",
      "YJ",
      "YK",
      "BE",
      "K1"
    ],
    "isETFSec": false,
    "isDelisted": false,
    "isin": "INE148I01020",
    "slb_isin": "INE148I01020",
    "listingDate": "2013-07-23",
    "isMunicipalBond": false,
    "isHybridSymbol": false,
    "segment": "EQUITY",
    "quotepreopenstatus": {
      "equityTime": "24-Mar-2026 16:00:00",
      "preOpenTime": "24-Mar-2026 09:07:56",
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
  "symbol": "GMRAIRPORT",
  "identifier": "",
  "series": "EQ",
  "open": "88",
  "dayHigh": "90.34",
  "dayLow": "86.95",
  "lastPrice": "89",
  "previousClose": "84.77",
  "change": 4.23,
  "pChange": 4.99,
  "totalTradedVolume": 15094837,
  "totalTradedValue": 1338006351.68,
  "yearHigh": "110.36",
  "yearLow": "74.96",
  "nearWKH": 19.35483870967742,
  "nearWKL": -18.72998932764142,
  "perChange365d": 14.25,
  "perChange30d": -10.76,
  "date365dAgo": "24-Mar-2025",
  "date30dAgo": "20-Feb-2026",
  "chartTodayPath": "https://nsearchives.nseindia.com/today/GMRAIRPORTEQN.svg",
  "chart30dPath": "https://nsearchives.nseindia.com/30d/GMRAIRPORT-EQ.svg",
  "chart365dPath": "https://nsearchives.nseindia.com/365d/GMRAIRPORT-EQ.svg",
  "meta": {
    "symbol": "GMRAIRPORT",
    "companyName": "GMR AIRPORTS LIMITED",
    "industry": "Airport & Airport services",
    "activeSeries": [
      "EQ",
      "T0"
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
    "isin": "INE776C01039",
    "slb_isin": "INE776C01039",
    "listingDate": "2006-08-21",
    "isMunicipalBond": false,
    "isHybridSymbol": false,
    "segment": "EQUITY",
    "quotepreopenstatus": {
      "equityTime": "24-Mar-2026 16:00:00",
      "preOpenTime": "24-Mar-2026 09:07:56",
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
Response: List of 125 items
Sample item (first):
{
  "date": "23-Mar-2026",
  "symbol": "ADANIENT",
  "name": "ADANI ENTERPRISES LIMITED",
  "clientName": null,
  "buySell": null,
  "qty": "6895",
  "watp": null,
  "remarks": null
}

============================================================
  GET /api/market/change-ranges/{symbol}
============================================================
Status: 200
{
  "oneDayPercent": -10.26,
  "oneWeekPercent": 1.17,
  "oneMonthPercent": -1.04,
  "threeMonthPercent": -9.25,
  "sixMonthPercent": 2.24,
  "oneYearPercent": 8.59,
  "twoYearPercent": -2.82,
  "threeYearPercent": 28.35,
  "fiveYearPercent": 38.13
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
        "lastPrice": 1414,
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
        "open": 1420,
        "dayHigh": 1422.4,
        "dayLow": 1406.6,
        "previousClose": 1407.8,
        "averagePrice": 1413.2,
        "change": 6.2,
        "pChange": 0.44,
        "basePrice": 1407.8,
        "closePrice": 1411.8,
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
        "totalTradedVolume": 18620893,
        "totalTradedValue": 26315045987.6,
        "series": "EQ",
        "lastPrice": 1414,
        "issuedSize": 13532472634,
        "basePrice": 1407.8,
        "ffmc": 9520711551706.17,
        "faceValue": 10,
        "impactCost": 0.01,
        "deliveryToTradedQuantity": 50.52,
        "applicableMargin": 12.5,
        "marketLot": null,
        "quantitytraded": 18620893,
        "deliveryquantity": 9406770,
        "totalMarketCap": 19134916304476,
        "secwisedelposdate": "24-Mar-2026 00:00:00"
      },
      "priceInfo": {
        "yearHightDt": "05-Jan-2026 00:00:00",
        "yearLowDt": "07-Apr-2025 00:00:00",
        "yearHigh": 1611.8,
        "yearLow": 1114.85,
        "priceBand": "1270.70-1552.90",
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
        "pdSectorPe": "19.55",
        "pdSymbolPe": "19.55",
        "isSuspended": "Active",
        "basicIndustry": "Refineries & Marketing",
        "index": "Nifty 50",
        "deliveryQuantity": "9406770",
        "deliveryTotradedQuantity": "50.52",
        "securityvar": "8.15",
        "indexvar": "0",
        "extremelossMargin": "3.5",
        "varMargin": "9",
        "adhocMargin": "0",
        "applicableMargin": "12.5",
        "bondType": null,
        "issueDesc": "Reliance Industries Ltd",
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
      "lastUpdateTime": "24-Mar-2026 16:00:00"
    }
  ]
}

============================================================
  GET /api/market/52week-low
============================================================
Status: 200
Top-level keys: ['data', 'low', 'timestamp']
data: List of 413 items
Sample item (first):
{
  "symbol": "21STCENMGM",
  "series": "EQ",
  "comapnyName": "21st Century Management Services Limited",
  "new52WHL": 30.65,
  "prev52WHL": 31.27,
  "prevHLDate": "23-Mar-2026",
  "ltp": 30.7,
  "prevClose": "31.27",
  "change": -0.57,
  "pChange": -1.8228333866325552
}

============================================================
  GET /api/market/52week-high
============================================================
Status: 200
Top-level keys: ['high', 'data', 'timestamp']
data: List of 14 items
Sample item (first):
{
  "symbol": "AETHER",
  "series": "EQ",
  "comapnyName": "Aether Industries Limited",
  "new52WHL": 1250,
  "prev52WHL": 1180,
  "prevHLDate": "20-Mar-2026",
  "ltp": 1179,
  "prevClose": "1085.05",
  "change": 93.95,
  "pChange": 8.658587161881941
}

============================================================
  GET /api/market/volume-gainers
============================================================
Status: 200
Top-level keys: ['data', 'timestamp']
data: List of 25 items
Sample item (first):
{
  "symbol": "MANGLMCEM",
  "companyName": "Mangalam Cement Limited",
  "volume": 1062426,
  "week1AvgVolume": 73463,
  "week1volChange": 14.462055728734192,
  "week2AvgVolume": 64167,
  "week2volChange": 16.55720230024779,
  "ltp": 828.75,
  "pChange": 2.58,
  "turnover": 676.02508
}

============================================================
  GET /api/market/largedeal-snapshot
============================================================
Status: 200
Top-level keys: ['as_on_date', 'BULK_DEALS_DATA', 'BULK_DEALS', 'SHORT_DEALS', 'BLOCK_DEALS', 'SHORT_DEALS_DATA', 'BLOCK_DEALS_DATA']
BULK_DEALS_DATA: 173 items
Sample BULK_DEALS_DATA item (first):
{
  "date": "24-Mar-2026",
  "symbol": "AGIIL",
  "name": "Agi Infra Limited",
  "clientName": "ARIHANT CAPITAL MARKETS LIMITED",
  "buySell": "BUY",
  "qty": "865468",
  "watp": "305.29",
  "remarks": "-"
}
BLOCK_DEALS_DATA: 7 items
Sample BLOCK_DEALS_DATA item (first):
{
  "date": "24-Mar-2026",
  "symbol": "JINDALPOLY",
  "name": "Jindal Poly Films Limited",
  "clientName": "MONET SECURITIES PRIVATE LTD",
  "buySell": "BUY",
  "qty": "354500",
  "watp": "888",
  "remarks": null
}
SHORT_DEALS_DATA: 125 items
Sample SHORT_DEALS_DATA item (first):
{
  "date": "23-Mar-2026",
  "symbol": "ADANIENT",
  "name": "ADANI ENTERPRISES LIMITED",
  "clientName": null,
  "buySell": null,
  "qty": "6895",
  "watp": null,
  "remarks": null
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
    "market_cap": "19,11,261 Cr.",
    "price": "1,412",
    "pe": "24.9",
    "book_value": "648",
    "dividend_yield": "0.39%",
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
    "opm": "17.4%",
    "profit_after_tax": "76,747Cr.",
    "mar_cap": "19,11,261Cr.",
    "sales_qtr": "2,64,905Cr.",
    "price_to_earning": "24.9",
    "price_to_book_value": "2.18",
    "industry_pe": "13.9",
    "current_price": "1,412",
    "price_to_sales": "1.87",
    "peg_ratio": "4.64",
    "pat_qtr": "18,645Cr.",
    "qtr_sales_var": "10.4%",
    "qtr_profit_var": "0.57%",
    "pledged_percentage": "0.00%",
    "debt": "3,74,593Cr.",
    "eps": "61.5",
    "evebitda": "10.9",
    "sales_last_year": "9,62,820Cr.",
    "op_ann": "1,65,598Cr.",
    "ebidt_last_year": "1,82,019Cr.",
    "dep_ann": "53,136Cr.",
    "ebit_last_year": "1,28,883Cr.",
    "pbt_ann": "1,06,017Cr.",
    "interest_last_year": "24,269Cr.",
    "tax_last_year": "25,230Cr.",
    "pat_ann": "68,732Cr.",
    "rsi": "51.0",
    "macd": "-5.05",
    "market_cap_to_sales": "1.87",
    "debt_to_profit": "4.61",
    "graham": "947",
    "altman_z_score": "2.86",
    "chg_in_fii_hold": "0.44%",
    "chg_in_dii_hold": "-0.15%",
    "earnings_yield": "6.57%"
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
  GET /api/news/global
============================================================
Status: 200
Response: List of 894 items
Sample item (first):
{
  "url": "https://www.moneycontrol.com/news/business/markets/sebi-proposes-gift-cards-for-mutual-funds-to-boost-retail-participation-13869333.html",
  "source": "moneycontrol_global",
  "title": "SEBI proposes \u2018gift cards\u2019 for mutual funds to boost retail participation",
  "text": "SEBI proposes \u2018gift cards\u2019 for mutual funds to boost retail participationThe idea, originally suggested by the Association of Mutual Funds in India (AMFI), aims to tap into gifting culture to drive financial inclusion.Moneycontrol NewsMarch 24, 2026/ 16:45 ISTSEBI proposes \u2018Gift Cards\u2019 for Mutual funds to boost retail participationSEBI proposes prepaid gift cards for mutual fund investmentsGift cards capped at Rs 10,000, valid for one year onlyGift card, e-wallet, cash investments capped at Rs 50k/yearDid our AI summary help?Market regulator Securities and Exchange Board of India (SEBI) has proposed an interesting mechanism to widen retail participation in mutual funds by allowing investments through prepaid \u2018gift cards\u2019, marking a potential shift in how first-time investors are onboarded into financial markets.In a consultation paper released on Tuesday, SEBI outlined a framework for introducing Gift Prepaid Payment Instruments (Gift PPIs), which would enable individuals to purchase a prepaid card and gift it to others for investing in mutual fund schemes. The proposal, if implemented, could transform mutual fund investing into a more accessible and socially shareable financial activity.Story continues below AdvertisementRemove AdThe idea, originally suggested by the Association of Mutual Funds in India (AMFI), aims to tap into gifting culture to drive financial inclusion. Under the proposed structure, a purchaser can buy a Gift PPI through banking channels or UPI, transfer it to a recipient, who can then redeem it on an asset management company\u2019s (AMC) platform to invest in mutual fund units.SEBI noted that such an instrument could help bring new investors, particularly those unfamiliar with traditional investment processes, into the mutual fund ecosystem.However, the regulator has proposed a detailed set of safeguards to prevent misuse and ensure compliance with existing norms. The Gift PPIs will remain governed by the Reserve Bank of India (RBI) guidelines for prepaid instruments, while the actual investment in mutual funds will fall under SEBI regulations.Related StoriesSEBI panel backs phased entry of FPIs into commodity derivatives, favours cash-settlement modelSEBI says disclosure norms under constant review; Framework being strengthenedAlso read:SEBI panel backs phased entry of FPIs into commodity derivatives, favours cash-settlement modelAs per RBI rules, the maximum value of a Gift PPI will be capped at Rs 10,000, and the instrument cannot be reloaded or used for cash withdrawal. SEBI has further proposed that such gift cards should be funded only through bank transfers or UPI, tightening the audit trail and reducing the risk of anonymous transactions.A key feature of the proposal is the emphasis on ownership verification. Before using the gift card, the recipient must formally claim ownership, which will then be verified against the mutual fund folio. Any mismatch will lead to rejection of the transaction and refund of funds. This is aimed at maintaining compliance with the strict \u201cno third-party payment\u201d rule applicable to mutual fund investments.Story continues below AdvertisementRemove AdThe proposal also seeks to maintain existing limits on small-ticket investments. Investments through Gift PPIs, along with e-wallets and cash, will be capped at Rs 50,000 per investor per mutual fund in a financial year.To simplify the user experience, SEBI has suggested that the full value of the gift card must be invested at once, preventing residual balances from remaining unutilized. Additionally, each Gift PPI will have a validity of one year, after which unused funds will be refunded to the purchaser\u2019s bank account.Recognizing that many recipients could be first-time investors, SEBI has proposed two pathways for investment decisions. The gift purchaser may suggest a mutual fund scheme, though the recommendation will not be binding. Alternatively, the recipient may seek assistance from a distributor, in which case the investment would be routed through the regular plan.Importantly, SEBI has clarified that no incentives such as cashback or promotional rewards can be linked to such investments, maintaining a level playing field and avoiding mis-selling.The regulator has invited public comments on key aspects of the proposal, including the role of distributors, refund mechanisms, and adequacy of safeguards. Feedback can be submitted until April 14, 2026.Also read:SC dismisses Avadhut Sathe Trading Academy plea but allows Rs 2.25-crore withdrawal for expensesMoneycontrol Newsfirst published: Mar 24, 2026 04:45 pmDiscover the latestBusiness News,Sensex, andNiftyupdates. ObtainPersonal Financeinsights, tax queries, and expert opinions onMoneycontrolor download theMoneycontrol Appto stay updated!AdvertisementRemove AdWatchPauseIran-US War Update: \u201cNo War\u201d Starmer Rejects Iran Conflict, Announces \u00a353M Support PlanUS-Iran War Update: \u201cWe Didn\u2019t Start This\u201d Germany Rejects Trump\u2019s Push for Action Against IranReliance Foundation Chairperson Nita Ambani Visits KISS to Receive Humanitarian AwardThe Truth Behind Sensex Always Being Higher Than NiftySushil Kedia on Market Technicals: Nifty Down 14% \u2014 Buy Signal Ahead?Watch moreSubscribe toTech NewslettersAl Edge NewsletterOn SaturdaysFind the best of Al News in one place, specially curated for you every\n        weekend.MC Tech 3 NewsletterDaily-WeekdaysStay on top of the latest tech trends and biggest startup news.Email address*SubscribeTrending newsIndian founder in UK says Ozempic helped lose 30kg in 8 months, but 'at a cost\u2019. Lists side effects'Just learn cooking': Swiggy hikes platform fee by 17% to Rs 17.58 after Zomato. Internet reactsZeroGPT flags Jawahar Lal Nehru\u2019s independence speech 'Tryst with Destiny' as AI-generatedAthiya Shetty and KL Rahul celebrate daughter Evaarah\u2019s first birthday with love-filled celebrationDhurandhar 2: Do you know Chaudhary Aslam was a Sanjay Dutt fan? He was known as \u2018Baba Cop\u2019 after KhalnayakIndia's 1st Transgender English Professor: Meet Dr N Jency \u2014  first trans woman to earn a PhD in Tamil Nadu3 feet tall doctor once offered Rs 5 lakh to join a circus \u2014 story of Dr Ganesh Bariya, mocked for his height but never gave upHe watched his country disappear from space: Meet astronaut Sergei Krikalev, who returned to a country that no longer existedRam Navami 2026 date: Is Shri Ram Janmotsav on March 26 or 27? Check correct date, puja timings and significanceTravel trends shift as Middle East disruptions push Indian travellers towards Asia and domestic destinations: ReportUS-Iran war impact: Amazon AWS outage hits Bahrain cloud region for second time this monthFather builds piano learning app for daughter using Claude; says, \u201cShe\u2019s now using it and...\u201dKidney disease is called silent killer for a reason, 3 early symptoms that go unnoticed and prevention tipsHigh blood pressure: Hidden region in brain that controls how you breathe out can cause hypertensionToo much protein in daily diet is not good for your gut health, warns NHS surgeon",
  "authors": null,
  "top_image": "https://images.moneycontrol.com/static-mcnews/2025/10/20251031065616_SEBI2.jpg",
  "publish_date": null,
  "fetched_at": "2026-03-24T18:15:38.667906",
  "created_at": "2026-03-24T18:15:45",
  "company_symbol": null
}

============================================================
  GET /api/news/company/{symbol}
============================================================
Status: 200
Response: List of 10 items
Sample item (first):
{
  "url": "https://www.moneycontrol.com/news/business/stocks/buy-reliance-industries-target-of-rs-1750-motilal-oswal-2-13858981.html",
  "source": "moneycontrol_company",
  "title": "Buy Reliance Industries; target of Rs 1750: Motilal Oswal",
  "text": "Buy Reliance Industries; target of Rs 1750: Motilal OswalMotilal Oswal is bullish on Reliance Industries recommended buy rating on the stock with a target price of Rs 1750 in its research report dated March 12, 2026.Broker ResearchMarch 13, 2026/ 09:34 ISTBuyRIRIWatchlistPortfolioMessageFollowNSE/BSE SelectNSE LIVEBSE LIVETradeDay HighDay LowVolume (NSE)More\u00d7Add to Watchlist\u00d7Motilal Oswal's research report onReliance IndustriesBlockade of the Strait of Hormuz (SoH) (~20% of global oil/LNG supply), ~3-4mb/d of refining capacity disruptions, refined product export restrictions in China, and decade-high crude freight rates have lifted gasoil/gasoline/jet fuel cracks to USD42/16/58 per bbl in Mar\u201926\u2019TD, 147%/40%/124% above LTA. PE and PX prices also rose 10-15% MoM in Mar\u201926\u2019TD. We believe that even if tensions ease soon, supply chain normalization may lag, keeping product cracks elevated and supporting Reliance Industries\u2019 (RIL) refiningpetchem margins.Story continues below AdvertisementRemove AdOutlookWe assign INR174/sh to the New Energy business, INR30/share equity value to RCPL, and INR26/sh to RIL\u2019s stake in JioStar. We reiterate our BUY rating with a TP of INR1,750.For all recommendations report,click hereRelated StoriesBuy Tata Power; target of Rs 455: Motilal OswalBuy HDFC AMC; target of Rs 2700: Motilal OswalBuy Aurobindo Pharma; target of Rs 1500: Motilal OswalDisclaimer:\u00a0The views and investment tips expressed by investment experts/broking houses/rating agencies on moneycontrol.com are their own, and not that of the website or its management. Moneycontrol.com advises users to check with certified experts before taking any investment decisions.Reliance Industries - 1303026 - motiBroker Researchfirst published: Mar 13, 2026 09:33 amDiscover the latestBusiness News,Sensex, andNiftyupdates. ObtainPersonal Financeinsights, tax queries, and expert opinions onMoneycontrolor download theMoneycontrol Appto stay updated!AdvertisementRemove AdWatchPauseIran-US War Update: \u201cNo War\u201d Starmer Rejects Iran Conflict, Announces \u00a353M Support PlanUS-Iran War Update: \u201cWe Didn\u2019t Start This\u201d Germany Rejects Trump\u2019s Push for Action Against IranReliance Foundation Chairperson Nita Ambani Visits KISS to Receive Humanitarian AwardThe Truth Behind Sensex Always Being Higher Than NiftySushil Kedia on Market Technicals: Nifty Down 14% \u2014 Buy Signal Ahead?Watch moreSubscribe toTech NewslettersAl Edge NewsletterOn SaturdaysFind the best of Al News in one place, specially curated for you every\n        weekend.MC Tech 3 NewsletterDaily-WeekdaysStay on top of the latest tech trends and biggest startup news.Email address*SubscribeTrending newsIndian founder in UK says Ozempic helped lose 30kg in 8 months, but 'at a cost\u2019. Lists side effects'Just learn cooking': Swiggy hikes platform fee by 17% to Rs 17.58 after Zomato. Internet reactsZeroGPT flags Jawahar Lal Nehru\u2019s independence speech 'Tryst with Destiny' as AI-generatedAthiya Shetty and KL Rahul celebrate daughter Evaarah\u2019s first birthday with love-filled celebrationDhurandhar 2: Do you know Chaudhary Aslam was a Sanjay Dutt fan? He was known as \u2018Baba Cop\u2019 after KhalnayakIndia's 1st Transgender English Professor: Meet Dr N Jency \u2014  first trans woman to earn a PhD in Tamil Nadu3 feet tall doctor once offered Rs 5 lakh to join a circus \u2014 story of Dr Ganesh Bariya, mocked for his height but never gave upHe watched his country disappear from space: Meet astronaut Sergei Krikalev, who returned to a country that no longer existedRam Navami 2026 date: Is Shri Ram Janmotsav on March 26 or 27? Check correct date, puja timings and significanceTravel trends shift as Middle East disruptions push Indian travellers towards Asia and domestic destinations: ReportUS-Iran war impact: Amazon AWS outage hits Bahrain cloud region for second time this monthFather builds piano learning app for daughter using Claude; says, \u201cShe\u2019s now using it and...\u201dKidney disease is called silent killer for a reason, 3 early symptoms that go unnoticed and prevention tipsHigh blood pressure: Hidden region in brain that controls how you breathe out can cause hypertensionToo much protein in daily diet is not good for your gut health, warns NHS surgeon",
  "authors": null,
  "top_image": "https://images.moneycontrol.com/static-mcnews/2025/11/20251118070809_Buy_1280x720_3.png",
  "publish_date": null,
  "fetched_at": "2026-03-24T17:52:56.978454",
  "created_at": "2026-03-13T22:19:14",
  "company_symbol": "RELIANCE"
}

============================================================
  GET /api/markets/industries
============================================================
Status: 200
Response: List of 190 items
Sample item (first):
{
  "category_type": "industry",
  "slug": "abrasives",
  "name": "Abrasives",
  "url": "https://www.moneycontrol.com/markets/industry-analysis/abrasives/",
  "market_cap": 31396.0,
  "pe": 42.53,
  "advance": 4,
  "decline": 1,
  "sentiment": "Bearish",
  "earnings_yoy": 0.164,
  "last_updated": "2026-03-24T08:01:06.698343",
  "created_at": "2026-03-14T19:47:09"
}

============================================================
  GET /api/markets/sectors
============================================================
Status: 200
Response: List of 39 items
Sample item (first):
{
  "category_type": "sector",
  "slug": "agri",
  "name": "Agri",
  "url": "https://www.moneycontrol.com/markets/sector-analysis/agri/",
  "market_cap": 307702.0,
  "pe": 26.08,
  "advance": 86,
  "decline": 62,
  "sentiment": "Bearish",
  "earnings_yoy": 0.3,
  "last_updated": "2026-03-24T07:51:28.063279",
  "created_at": "2026-03-14T19:49:11"
}

============================================================
  GET /api/markets/industries/{slug}/stocks
============================================================
Status: 200
Response: List of 28 items
Sample item (first):
{
  "id": 1695,
  "symbol": "HDF01",
  "company_name": "HDFC Bank",
  "exchange": "NSE",
  "curr_price": 764.9,
  "per_change": 2.79,
  "market_cap": 1177332.0,
  "ttm_pe": 15.8,
  "net_profit": 20691.0,
  "net_profit_yoy": 12.82,
  "tech_trend": "Very Bearish",
  "mc_url": "https://www.moneycontrol.com/india/stockpricequote/banks-private-sector/hdfcbank/HDF01",
  "categories": [
    {
      "type": "industry",
      "slug": "bank-private"
    },
    {
      "type": "sector",
      "slug": "banks"
    }
  ],
  "last_updated": "2026-03-24T18:40:43.701701",
  "created_at": "2026-03-14T18:13:30"
}

============================================================
  GET /api/markets/sectors/{slug}/stocks
============================================================
Status: 200
Response: List of 40 items
Sample item (first):
{
  "id": 1695,
  "symbol": "HDF01",
  "company_name": "HDFC Bank",
  "exchange": "NSE",
  "curr_price": 764.9,
  "per_change": 2.79,
  "market_cap": 1177332.0,
  "ttm_pe": 15.8,
  "net_profit": 20691.0,
  "net_profit_yoy": 12.82,
  "tech_trend": "Very Bearish",
  "mc_url": "https://www.moneycontrol.com/india/stockpricequote/banks-private-sector/hdfcbank/HDF01",
  "categories": [
    {
      "type": "industry",
      "slug": "bank-private"
    },
    {
      "type": "sector",
      "slug": "banks"
    }
  ],
  "last_updated": "2026-03-24T18:40:43.701701",
  "created_at": "2026-03-14T18:13:30"
}

============================================================
  GET /api/morningstar/fairvalue/{symbol}
============================================================
Status: 200
{
  "symbol": "TCS",
  "morningstarId": "792760B1-C368-4050-A8D7-BBAD450E2522",
  "fairValue": null,
  "updatedAt": null
}

============================================================
  GET /api/morningstar/search
============================================================
Status: 200
Response: List of 1 items
Sample item (first):
{
  "symbol": "RELIANCE",
  "morningstarId": "5D9AA6FB-DD57-4A9F-B5FD-287A1B5015B2"
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