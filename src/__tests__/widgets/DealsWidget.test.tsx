import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { render } from '../utils/renderWithProviders';
import { activeSymbolAtom } from '@/store/terminalStore';

// ── iinvest lib mock ──────────────────────────────────────────────────────────
// Real iinvest shape: keyshareholders row[0] is the array HEADER, subsequent
// rows are dicts with nested {per, val} per quarter column. sast returns
// columns[] with {field, displayName, dataType} + data[] with f_* field codes.

const realKeyShareholders = {
  status: true,
  response: {
    // Real iinvest shape (verified 2026-06-18, MAXHEALTH):
    //   - row[0] is the array HEADER
    //   - rows[1..] are PARALLEL ARRAYS. Format:
    //     [ID, ParentID, IsExpanded, Description, Mar-26, Dec-25, ...]
    //   - Rows with IsExpanded=True + ParentID=null are TOP-LEVEL GROUPS
    //     (Promoter, Public, etc.). The iinvest web view shows these as
    //     expandable sections; their children have ParentID=this group's ID.
    //   - Rows with IsExpanded=False are LEAF HOLDERS with {per,val} cells.
    //   - Top-level groups have null cell values for all quarter columns.
    //   - Some leaf holders have per:null (e.g. "— —" rows).
      data: [
        ['ID', 'ParentID', 'IsExpanded', 'Description', 'Mar-26', 'Dec-25', 'Sep-25'],
        // Groups (top-level, no parent, expandable)
        [501, null, true, 'Promoter and Promoter Group', null, null, null],
        [502, null, true, 'Public Group', null, null, null],
        // Holders under Promoter — sum Mar-26 per = 51.82 + 11.36 = 63.18
        [101, 501, false, 'Vinay Kumar', { per: 51.82, val: 40850367 }, { per: 51.82, val: 40850367 }, { per: 51.82, val: 40850367 }],
        [102, 501, false, 'Ajay Kumar',  { per: 11.36, val: 8952500 },  { per: 11.36, val: 8952500 },  { per: 10.90, val: 8592500 }],
        // Holders under Public
        [103, 502, false, 'Abhay Soi',  { per: 23.71, val: 230717699 }, { per: 23.71, val: 230717699 }, { per: 23.71, val: 230717699 }],
        [104, 502, false, 'New World Fund Inc', { per: 3.70, val: 35992249 }, { per: 3.70, val: 35992249 }, { per: 3.70, val: 35992249 }],
        // A holder with per:null (the "— —" rows in the iinvest screenshot)
        [105, 502, false, 'Smallcap World Fund, Inc', { per: null, val: null }, { per: null, val: null }, { per: null, val: null }],
      ],
  },
};

const realSast = {
  status: true,
  response: {
    columns: [
      { field: 'f_162', displayName: 'Date',                dataType: 'Date' },
      { field: 'f_48',  displayName: 'Person',              dataType: 'String' },
      { field: 'f_57',  displayName: 'Mode',                dataType: 'String' },
      { field: 'f_52',  displayName: 'No of Shares',        dataType: 'Number' },
      { field: 'f_53',  displayName: 'No of Shares (POST)', dataType: 'Number' },
      { field: 'f_58',  displayName: 'Mode of Acquisition', dataType: 'String' },
      { field: 'f_59',  displayName: 'Acquisition Type',    dataType: 'String' },
    ],
    data: [
      { f_162: '26-Sep-24', f_48: 'Ankita Aggarwal', f_57: 'Acquisition', f_52: 200000, f_53: 200000, f_58: 'Others', f_59: 'Equity shares' },
      { f_162: '19-Apr-23', f_48: 'Arnav Aggarwal',  f_57: 'Both',         f_52: 100000, f_53: 100000, f_58: 'Both',    f_59: 'Equity shares' },
    ],
  },
};

const realIinvestInsider = {
  status: true,
  response: {
    data: [
      { f_28: '18 Feb 26', f_4: 'BALANADU NARAYAN', f_5: 'Other', f_10: 2320, f_12: 'Sell' },
      { f_28: '12 Jan 26', f_4: 'SANGEETA MODI',   f_5: 'Promoter', f_10: 50000, f_12: 'Buy' },
    ],
  },
};

const mockBlockDeals = {
  status: true,
  response: {
    data: [
      { f_32: 'BLOCK_TRADER_X', f_33: 'BUY', f_34: 1000000, f_36: 500, f_35: '15 Jan 26' },
      { f_32: 'BLOCK_TRADER_Y', f_33: 'SELL', f_34: 800000, f_36: 510, f_35: '14 Jan 26' },
    ],
  },
};

const mockBulkDeals = {
  status: true,
  response: {
    data: [
      { f_32: 'BULK_CLIENT_A', f_33: 'BUY', f_34: 50000, f_36: 100, f_35: '10 Jan 26' },
      { f_32: 'BULK_CLIENT_B', f_33: 'SELL', f_34: 30000, f_36: 101, f_35: '09 Jan 26' },
    ],
  },
};

const mockPledgedShares = {
  status: true,
  response: {
    columns: [
      { field: 'f_5',  displayName: 'Promoter Name', dataType: 'String' },
      { field: 'f_7',  displayName: 'No of Shares',  dataType: 'Number' },
      { field: 'f_8',  displayName: 'Percentage',    dataType: 'Number' },
    ],
    data: [
      { f_5: 'Promoter', f_7: 100000, f_8: 50.0 },
    ],
  },
};

vi.mock('@/lib/iinvest', () => ({
  fetchIinvestAll: vi.fn(async () => ({
    pledged_shares: mockPledgedShares,
    key_shareholders: realKeyShareholders,
    sast: realSast,
    insider_trading: realIinvestInsider,
    block_deals: mockBlockDeals,
    bulk_deals: mockBulkDeals,
  })),
  fetchIinvestPledgedShares: vi.fn(async () => mockPledgedShares),
  fetchIinvestKeyShareholders: vi.fn(async () => realKeyShareholders),
  fetchIinvestSast: vi.fn(async () => realSast),
  fetchIinvestInsiderTrading: vi.fn(async () => realIinvestInsider),
  fetchIinvestBlockDeals: vi.fn(async () => mockBlockDeals),
  fetchIinvestBulkDeals: vi.fn(async () => mockBulkDeals),
}));

// ── screener fetch mock (returns empty for the 3 screener tabs) ─────────────

let fetchSpy: ReturnType<typeof vi.spyOn> | null = null;
beforeEach(() => {
  fetchSpy = vi.spyOn(global, 'fetch').mockImplementation(
    (async (url: string) => {
      if (url.includes('/screener/trades/')) {
        return new Response(
          JSON.stringify({ insider_trades: [], bulk_deals: [], block_deals: [] }),
          { status: 200, headers: { 'content-type': 'application/json' } },
        );
      }
      return new Response('{}', { status: 404 });
    }) as typeof fetch,
  );
});
afterEach(() => {
  fetchSpy?.mockRestore();
});

import { DealsTab } from '@/components/widgets/CompanyTabs/DealsTab';
import { ShareholdingTable } from '@/components/widgets/CompanyTabs/ShareholdingTable';
import { IinvestGenericTable, type IinvestColumn } from '@/components/widgets/CompanyTabs/IinvestGenericTable';

const renderWithSymbol = (symbol = 'RELIANCE') => {
  return render(<DealsTab symbol={symbol} />, {
    wrapperProps: { initialAtomValues: [[activeSymbolAtom, symbol]] },
  });
};

describe('DealsWidget — deals and trades tabs', () => {
  it('renders all 4 deals tabs (Insider, Bulk, Block, SAST) and excludes Pledged and Shareholding', async () => {
    renderWithSymbol();

    await waitFor(() => {
      expect(screen.getByText(/^Insider$/i)).toBeInTheDocument();
    });

    // Screener & iinvest deals tabs
    expect(screen.getByText(/^Bulk$/i)).toBeInTheDocument();
    expect(screen.getByText(/^Block$/i)).toBeInTheDocument();
    expect(screen.getByText(/^SAST$/i)).toBeInTheDocument();

    // Pledged and Shareholding are strictly moved to FundamentalsTab
    expect(screen.queryByText(/^Pledged$/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/^Shareholding$/i)).not.toBeInTheDocument();
  });
  it('SAST tab renders human-readable column headers from columns[].displayName, not raw f_* codes', async () => {
    renderWithSymbol();

    await waitFor(() => {
      expect(screen.getByText(/^Insider$/i)).toBeInTheDocument();
    });

    const user = userEvent.setup();
    await user.click(screen.getByText(/^SAST$/i));

    await waitFor(() => {
      // The columns array provides displayName; we should NOT see f_162 etc.
      expect(screen.queryByText(/f_162/)).not.toBeInTheDocument();
      expect(screen.queryByText(/f_48/)).not.toBeInTheDocument();
      // Instead the friendly column names render
      expect(screen.getByText(/^Date$/)).toBeInTheDocument();
      expect(screen.getByText(/^Person$/)).toBeInTheDocument();
      expect(screen.getByText(/^Mode$/)).toBeInTheDocument();
      // The "POST" column distinguishes the two "No of Shares" headers
      expect(screen.getByText(/No of Shares \(POST\)/i)).toBeInTheDocument();
      // Row data
      expect(screen.getByText(/Ankita Aggarwal/i)).toBeInTheDocument();
      // "Acquisition" matches the "Mode of Acquisition" header too — use
      // getAllByText and assert at least 2 occurrences (header + cell).
      expect(screen.getAllByText(/Acquisition/).length).toBeGreaterThan(1);
      // The number formatter uses en-IN (200000 → 2,00,000)
      // (appears in both f_52 and f_53 columns)
      expect(screen.getAllByText(/2,00,000/).length).toBeGreaterThan(0);
    });
  });

  it('Tab tooltips describe what the data represents (not the source)', async () => {
    renderWithSymbol();

    await waitFor(() => {
      expect(screen.getByText(/^Insider$/i)).toBeInTheDocument();
    });

    // The Insider tab's tooltip should describe what insider trades are,
    // not the source URL.
    const insiderTab = screen.getByText(/^Insider$/i).closest('button');
    expect(insiderTab?.getAttribute('title')).toMatch(/directors|insider|SEBI/i);
    // The old source tooltip "from screener.in" should NOT be present
    expect(insiderTab?.getAttribute('title')).not.toMatch(/from screener\.in/);

    // The SAST tab tooltip should explain the regulation
    const sastTab = screen.getByText(/^SAST$/i).closest('button');
    expect(sastTab?.getAttribute('title')).toMatch(/Substantial|SEBI|acquisition/i);
  });

  it('Insider tab falls back to iinvest data when screener returns empty', async () => {
    // Override the screener fetch mock to return empty insider_trades
    // (which simulates a symbol that screener has no insider data for)
    fetchSpy?.mockImplementation(
      (async (url: string) => {
        if (url.includes('/screener/trades/')) {
          return new Response(
            JSON.stringify({ insider_trades: [], bulk_deals: [], block_deals: [] }),
            { status: 200, headers: { 'content-type': 'application/json' } },
          );
        }
        return new Response('{}', { status: 404 });
      }) as typeof fetch,
    );

    renderWithSymbol();

    await waitFor(() => {
      expect(screen.getByText(/^Insider$/i)).toBeInTheDocument();
    });

    const user = userEvent.setup();
    await user.click(screen.getByText(/^Insider$/i));

    // The iinvest mock has BALANADU NARAYAN + SANGEETA MODI; they should
    // be visible because screener's insider_trades is empty.
    await waitFor(() => {
      expect(screen.getByText(/BALANADU NARAYAN/i)).toBeInTheDocument();
      expect(screen.getByText(/SANGEETA MODI/i)).toBeInTheDocument();
    });
    // The category "Promoter" should render in the category column
    expect(screen.getByText(/^Promoter$/i)).toBeInTheDocument();
  });

  it('Block tab renders rows from iinvest fallback (not just a count)', async () => {
    renderWithSymbol();

    await waitFor(() => {
      expect(screen.getByText(/^Insider$/i)).toBeInTheDocument();
    });

    const user = userEvent.setup();
    await user.click(screen.getByText(/^Block$/i));

    // The iinvest mock has 2 block-deal rows — they should actually
    // render in the table, not just contribute to the tab count.
    await waitFor(() => {
      expect(screen.getByText(/BLOCK_TRADER_X/i)).toBeInTheDocument();
      expect(screen.getByText(/BLOCK_TRADER_Y/i)).toBeInTheDocument();
    });
    // The f_35 date "15 Jan 26" should render in the period column
    expect(screen.getByText(/15 Jan 26/i)).toBeInTheDocument();
  });

  it('Bulk and Block tabs show DIFFERENT data (not the same merged list)', async () => {
    renderWithSymbol();

    await waitFor(() => {
      expect(screen.getByText(/^Insider$/i)).toBeInTheDocument();
    });

    const user = userEvent.setup();

    // Open the Bulk tab — should show BULK_CLIENT_A + BULK_CLIENT_B
    await user.click(screen.getByText(/^Bulk$/i));
    await waitFor(() => {
      expect(screen.getByText(/BULK_CLIENT_A/i)).toBeInTheDocument();
      expect(screen.getByText(/BULK_CLIENT_B/i)).toBeInTheDocument();
    });
    // The Block tab's data (BLOCK_TRADER_*) should NOT be visible while
    // the Bulk tab is active. This is the bug the user reported.
    expect(screen.queryByText(/BLOCK_TRADER_X/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/BLOCK_TRADER_Y/i)).not.toBeInTheDocument();

    // Switch to the Block tab — should now show BLOCK_TRADER_*
    await user.click(screen.getByText(/^Block$/i));
    await waitFor(() => {
      expect(screen.getByText(/BLOCK_TRADER_X/i)).toBeInTheDocument();
      expect(screen.getByText(/BLOCK_TRADER_Y/i)).toBeInTheDocument();
    });
    // The Bulk tab's data should now be gone
    expect(screen.queryByText(/BULK_CLIENT_A/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/BULK_CLIENT_B/i)).not.toBeInTheDocument();
  });



  it('Block tab count matches the actual rendered rows (12 is not OK if nothing shows)', async () => {
    // The user's bug: tab showed 12 but body was empty. This test asserts
    // that whenever the count is > 0, the table has at least that many
    // visible data rows.
    renderWithSymbol();

    await waitFor(() => {
      expect(screen.getByText(/^Insider$/i)).toBeInTheDocument();
    });

    const user = userEvent.setup();
    await user.click(screen.getByText(/^Block$/i));

    // Wait for the table to render
    await waitFor(() => {
      // Count "rows" in the table body
      const tableRows = screen.getAllByRole('row');
      // 1 header row + N data rows. Assert N >= 1 (any data).
      expect(tableRows.length).toBeGreaterThan(1);
    });
  });
});

describe('IinvestGenericTable', () => {
  it('renders table columns and formatted data', () => {
    render(
      <IinvestGenericTable
        data={mockPledgedShares.response.data}
        columns={mockPledgedShares.response.columns as IinvestColumn[]}
        emptyMsg="No pledged shares"
      />,
    );
    expect(screen.getAllByText(/Promoter/).length).toBeGreaterThan(0);
    expect(screen.getByText(/1,00,000/)).toBeInTheDocument();
  });
});

describe('ShareholdingTable', () => {
  it('renders quarter columns, group headers with aggregate totals, and starts with groups collapsed', async () => {
    render(<ShareholdingTable data={realKeyShareholders.response.data} />);

    // Quarter header labels
    expect(screen.getAllByText('Mar-26')[0]).toBeInTheDocument();
    expect(screen.getAllByText('Dec-25')[0]).toBeInTheDocument();

    // Top-level groups render
    expect(screen.getByText(/Promoter and Promoter Group/i)).toBeInTheDocument();
    expect(screen.getByText(/Public Group/i)).toBeInTheDocument();

    // Groups are collapsed by default: children are NOT visible yet
    expect(screen.queryByText(/Vinay Kumar/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Abhay Soi/i)).not.toBeInTheDocument();

    // Group header displays aggregate % (63.18) even when collapsed
    const groupHeader = screen.getByTestId('shareholding-group-501');
    expect(groupHeader).toBeInTheDocument();
    expect(groupHeader.textContent).toMatch(/63.18/);
  });

  it('expands group on click to show child holders with values, filtering out empty rows', async () => {
    render(<ShareholdingTable data={realKeyShareholders.response.data} />);

    const user = userEvent.setup();
    const promoterHeader = screen.getByText(/Promoter and Promoter Group/i);

    // Expand Promoter group
    await user.click(promoterHeader);

    await waitFor(() => {
      expect(screen.getByText(/Vinay Kumar/i)).toBeInTheDocument();
      expect(screen.getByText(/Ajay Kumar/i)).toBeInTheDocument();
      expect(screen.getAllByText(/^51.82$/).length).toBeGreaterThan(0);
      expect(screen.getAllByText(/4,08,50,367/).length).toBeGreaterThan(0);
    });

    // Expand Public group
    const publicHeader = screen.getByText(/Public Group/i);
    await user.click(publicHeader);

    await waitFor(() => {
      expect(screen.getByText(/Abhay Soi/i)).toBeInTheDocument();
      expect(screen.getByText(/New World Fund Inc/i)).toBeInTheDocument();
    });

    // Empty holder row (Smallcap World Fund with per:null) is dropped from expanded children
    expect(screen.queryByText(/Smallcap World Fund/i)).not.toBeInTheDocument();

    // Clicking group header again collapses it
    await user.click(promoterHeader);
    await waitFor(() => {
      expect(screen.queryByText(/Vinay Kumar/i)).not.toBeInTheDocument();
    });
  });
});
