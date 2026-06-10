"""squash — linearized single migration
Revision ID: x999999999999
Revises: None
Create Date: 2026-06-09 21:20:44.031062
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import sqlite

# revision identifiers, used by Alembic.
revision: str = 'x999999999999'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'chat_sessions',
        sa.Column('id', sa.INTEGER, nullable=False, primary_key=True),
        sa.Column('user_id', sa.INTEGER, nullable=False, server_default=sa.text('1')),
        sa.Column('title', sa.VARCHAR(120), nullable=False, server_default=sa.text('New Chat')),
        sa.Column('model', sa.VARCHAR(64), nullable=False, server_default=sa.text('minimax-m2-5-free')),
        sa.Column('symbol', sa.VARCHAR(32), nullable=False, server_default=sa.text('')),
        sa.Column('exchange', sa.VARCHAR(16), nullable=False, server_default=sa.text('NSE')),
        sa.Column('created_at', sa.DATETIME, nullable=False),
        sa.Column('updated_at', sa.DATETIME, nullable=False)
    )
    op.create_table(
        'chat_messages',
        sa.Column('id', sa.INTEGER, nullable=False, primary_key=True),
        sa.Column('session_id', sa.INTEGER, nullable=False),
        sa.Column('role', sa.VARCHAR(16), nullable=False),
        sa.Column('content', sa.TEXT, nullable=False, server_default=sa.text('')),
        sa.Column('tool_calls_json', sa.TEXT, nullable=True),
        sa.Column('created_at', sa.DATETIME, nullable=False)
    )
    op.create_table(
        'corporate_filings',
        sa.Column('symbol', sa.VARCHAR(32), nullable=False, primary_key=True),
        sa.Column('csv_data', sa.TEXT, nullable=False),
        sa.Column('last_fetched_at', sa.DATETIME, nullable=False),
        sa.Column('created_at', sa.DATETIME, nullable=False),
        sa.Column('updated_at', sa.DATETIME, nullable=False)
    )
    op.create_table(
        'market_categories',
        sa.Column('category_type', sa.VARCHAR(32), nullable=False, primary_key=True),
        sa.Column('slug', sa.VARCHAR(128), nullable=False, primary_key=True),
        sa.Column('name', sa.VARCHAR(255), nullable=False),
        sa.Column('url', sa.VARCHAR(512), nullable=True),
        sa.Column('market_cap', sa.FLOAT, nullable=True),
        sa.Column('pe', sa.FLOAT, nullable=True),
        sa.Column('advance', sa.INTEGER, nullable=True),
        sa.Column('decline', sa.INTEGER, nullable=True),
        sa.Column('sentiment', sa.VARCHAR(32), nullable=True),
        sa.Column('earnings_yoy', sa.FLOAT, nullable=True),
        sa.Column('last_updated', sa.DATETIME, nullable=False),
        sa.Column('created_at', sa.DATETIME, nullable=False)
    )
    op.create_table(
        'market_category_stocks',
        sa.Column('id', sa.INTEGER, nullable=False, primary_key=True),
        sa.Column('symbol', sa.VARCHAR(32), nullable=False),
        sa.Column('company_name', sa.VARCHAR(255), nullable=False),
        sa.Column('exchange', sa.VARCHAR(16), nullable=True),
        sa.Column('curr_price', sa.FLOAT, nullable=True),
        sa.Column('per_change', sa.FLOAT, nullable=True),
        sa.Column('market_cap', sa.FLOAT, nullable=True),
        sa.Column('ttm_pe', sa.FLOAT, nullable=True),
        sa.Column('net_profit', sa.FLOAT, nullable=True),
        sa.Column('net_profit_yoy', sa.FLOAT, nullable=True),
        sa.Column('tech_trend', sa.VARCHAR(32), nullable=True),
        sa.Column('mc_url', sa.VARCHAR(512), nullable=True),
        sa.Column('categories', sa.JSON, nullable=False),
        sa.Column('last_updated', sa.DATETIME, nullable=False),
        sa.Column('created_at', sa.DATETIME, nullable=False)
    )
    op.create_table(
        'news_articles',
        sa.Column('url', sa.VARCHAR(2048), nullable=False, primary_key=True),
        sa.Column('source', sa.VARCHAR(64), nullable=False),
        sa.Column('title', sa.VARCHAR(512), nullable=True),
        sa.Column('text', sa.TEXT, nullable=True),
        sa.Column('authors', sa.JSON, nullable=True),
        sa.Column('top_image', sa.VARCHAR(2048), nullable=True),
        sa.Column('publish_date', sa.DATETIME, nullable=True),
        sa.Column('fetched_at', sa.DATETIME, nullable=False),
        sa.Column('created_at', sa.DATETIME, nullable=False),
        sa.Column('company_symbol', sa.VARCHAR(32), nullable=True),
        sa.Column('sentiment', sa.VARCHAR(16), nullable=True),
        sa.Column('sentiment_score', sa.FLOAT, nullable=True),
        sa.Column('confidence', sa.FLOAT, nullable=True),
        sa.Column('language', sa.VARCHAR(8), nullable=True),
        sa.Column('entities', sa.JSON, nullable=True),
        sa.Column('threat_level', sa.VARCHAR(16), nullable=True),
        sa.Column('threat_category', sa.VARCHAR(32), nullable=True),
        sa.Column('source_credibility', sa.VARCHAR(16), nullable=True)
    )
    op.create_table(
        'notifications',
        sa.Column('id', sa.INTEGER, nullable=False, primary_key=True),
        sa.Column('watchlist_id', sa.INTEGER, nullable=False),
        sa.Column('symbol', sa.VARCHAR(32), nullable=False),
        sa.Column('exchange', sa.VARCHAR(16), nullable=False, server_default=sa.text('NSE')),
        sa.Column('trigger_type', sa.VARCHAR(32), nullable=False),
        sa.Column('message', sa.VARCHAR(256), nullable=False),
        sa.Column('triggered_at', sa.DATETIME, nullable=False),
        sa.Column('triggered_date', sa.DATE, nullable=False),
        sa.Column('is_read', sa.BOOLEAN, nullable=False, server_default=sa.text('False'))
    )
    op.create_table(
        'global_notifications',
        sa.Column('id', sa.INTEGER, nullable=False, primary_key=True),
        sa.Column('symbol', sa.VARCHAR(32), nullable=False),
        sa.Column('exchange', sa.VARCHAR(16), nullable=False, server_default=sa.text('NSE')),
        sa.Column('trigger_type', sa.VARCHAR(32), nullable=False),
        sa.Column('message', sa.VARCHAR(256), nullable=False),
        sa.Column('triggered_at', sa.DATETIME, nullable=False),
        sa.Column('triggered_date', sa.DATE, nullable=False),
        sa.Column('is_read', sa.BOOLEAN, nullable=False, server_default=sa.text('False'))
    )
    op.create_table(
        'stock_universe',
        sa.Column('symbol', sa.VARCHAR(32), nullable=False, primary_key=True),
        sa.Column('series', sa.VARCHAR(8), nullable=True),
        sa.Column('company_name', sa.VARCHAR(255), nullable=False),
        sa.Column('segment', sa.VARCHAR(64), nullable=False),
        sa.Column('industry', sa.VARCHAR(255), nullable=False),
        sa.Column('sector_pe', sa.FLOAT, nullable=True),
        sa.Column('symbol_pe', sa.FLOAT, nullable=True),
        sa.Column('industry_info', sa.JSON, nullable=False),
        sa.Column('last_update_time', sa.DATETIME, nullable=True),
        sa.Column('screener_trades_id', sa.VARCHAR(32), nullable=True),
        sa.Column('mc_url', sa.VARCHAR(512), nullable=True),
        sa.Column('review_status', sa.VARCHAR(32), nullable=True),
        sa.Column('match_confidence', sa.FLOAT, nullable=True),
        sa.Column('mc_match_source', sa.VARCHAR(32), nullable=True),
        sa.Column('mc_company_name', sa.VARCHAR(255), nullable=True),
        sa.Column('morningstar_id', sa.VARCHAR(32), nullable=True),
        sa.Column('fair_value', sa.FLOAT, nullable=True),
        sa.Column('fair_value_updated_at', sa.DATETIME, nullable=True),
        sa.Column('high_52w', sa.FLOAT, nullable=True),
        sa.Column('low_52w', sa.FLOAT, nullable=True),
        sa.Column('high_52w_date', sa.DATETIME, nullable=True),
        sa.Column('low_52w_date', sa.DATETIME, nullable=True),
        sa.Column('high_52w_updated_at', sa.DATETIME, nullable=True),
        sa.Column('ticker_failure_count', sa.INTEGER, nullable=False),
        sa.Column('created_at', sa.DATETIME, nullable=False),
        sa.Column('updated_at', sa.DATETIME, nullable=False)
    )
    op.create_table(
        'ticker_daily',
        sa.Column('id', sa.INTEGER, nullable=False, primary_key=True),
        sa.Column('symbol', sa.VARCHAR(32), nullable=False),
        sa.Column('date', sa.DATE, nullable=False),
        sa.Column('series', sa.VARCHAR(4), nullable=False),
        sa.Column('open', sa.FLOAT, nullable=False),
        sa.Column('high', sa.FLOAT, nullable=False),
        sa.Column('low', sa.FLOAT, nullable=False),
        sa.Column('close', sa.FLOAT, nullable=False),
        sa.Column('volume', sa.BIGINT, nullable=False),
        sa.Column('value', sa.FLOAT, nullable=False),
        sa.Column('source', sa.VARCHAR(32), nullable=False),
        sa.Column('created_at', sa.DATETIME, nullable=False),
        sa.Column('rsi_14', sa.FLOAT, nullable=True),
        sa.Column('macd', sa.FLOAT, nullable=True),
        sa.Column('macd_signal', sa.FLOAT, nullable=True),
        sa.Column('macd_histogram', sa.FLOAT, nullable=True),
        sa.Column('bb_middle', sa.FLOAT, nullable=True),
        sa.Column('bb_upper', sa.FLOAT, nullable=True),
        sa.Column('bb_lower', sa.FLOAT, nullable=True),
        sa.Column('bb_width', sa.FLOAT, nullable=True),
        sa.Column('bb_squeeze', sa.VARCHAR(1), nullable=True),
        sa.Column('atr_14', sa.FLOAT, nullable=True),
        sa.Column('atr_percent', sa.FLOAT, nullable=True),
        sa.Column('vwma_20', sa.FLOAT, nullable=True),
        sa.Column('hv_20', sa.FLOAT, nullable=True),
        sa.Column('hv_60', sa.FLOAT, nullable=True),
        sa.Column('sharpe_60', sa.FLOAT, nullable=True),
        sa.Column('sharpe_126', sa.FLOAT, nullable=True),
        sa.Column('indicators_updated_at', sa.DATETIME, nullable=True)
    )
    op.create_table(
        'ticker_scores',
        sa.Column('id', sa.INTEGER, nullable=False, primary_key=True),
        sa.Column('symbol', sa.VARCHAR(32), nullable=False),
        sa.Column('compute_date', sa.DATE, nullable=False),
        sa.Column('computed_at', sa.DATETIME, nullable=False),
        sa.Column('return_1d', sa.FLOAT, nullable=True),
        sa.Column('return_1w', sa.FLOAT, nullable=True),
        sa.Column('return_1m', sa.FLOAT, nullable=True),
        sa.Column('return_3m', sa.FLOAT, nullable=True),
        sa.Column('return_6m', sa.FLOAT, nullable=True),
        sa.Column('return_1y', sa.FLOAT, nullable=True),
        sa.Column('momentum_score', sa.FLOAT, nullable=True),
        sa.Column('momentum_rank', sa.INTEGER, nullable=True),
        sa.Column('universe_size', sa.INTEGER, nullable=True),
        sa.Column('volume_ratio_20d', sa.FLOAT, nullable=True)
    )
    op.create_table(
        'ticker_screener_snapshot',
        sa.Column('symbol', sa.VARCHAR(32), nullable=False, primary_key=True),
        sa.Column('last_date', sa.DATE, nullable=False),
        sa.Column('compute_date', sa.DATE, nullable=False),
        sa.Column('computed_at', sa.DATETIME, nullable=False),
        sa.Column('last_close', sa.FLOAT, nullable=False),
        sa.Column('last_volume', sa.BIGINT, nullable=False),
        sa.Column('last_open', sa.FLOAT, nullable=False),
        sa.Column('last_high', sa.FLOAT, nullable=False),
        sa.Column('last_low', sa.FLOAT, nullable=False),
        sa.Column('rsi_1d', sa.FLOAT, nullable=True),
        sa.Column('macd_1d', sa.FLOAT, nullable=True),
        sa.Column('macd_signal_1d', sa.FLOAT, nullable=True),
        sa.Column('macd_histogram_1d', sa.FLOAT, nullable=True),
        sa.Column('bb_middle_1d', sa.FLOAT, nullable=True),
        sa.Column('bb_upper_1d', sa.FLOAT, nullable=True),
        sa.Column('bb_lower_1d', sa.FLOAT, nullable=True),
        sa.Column('bb_width_1d', sa.FLOAT, nullable=True),
        sa.Column('bb_squeeze_1d', sa.VARCHAR(1), nullable=True),
        sa.Column('atr_1d', sa.FLOAT, nullable=True),
        sa.Column('atr_percent_1d', sa.FLOAT, nullable=True),
        sa.Column('vwma_20_1d', sa.FLOAT, nullable=True),
        sa.Column('hv_20', sa.FLOAT, nullable=True),
        sa.Column('hv_60', sa.FLOAT, nullable=True),
        sa.Column('sharpe_60', sa.FLOAT, nullable=True),
        sa.Column('sharpe_126', sa.FLOAT, nullable=True),
        sa.Column('high_52w', sa.FLOAT, nullable=True),
        sa.Column('low_52w', sa.FLOAT, nullable=True),
        sa.Column('pct_from_52w_high', sa.FLOAT, nullable=True),
        sa.Column('pct_from_52w_low', sa.FLOAT, nullable=True),
        sa.Column('sector', sa.VARCHAR(64), nullable=True),
        sa.Column('industry', sa.VARCHAR(128), nullable=True),
        sa.Column('pe', sa.FLOAT, nullable=True),
        sa.Column('market_cap', sa.FLOAT, nullable=True),
        sa.Column('fair_value', sa.FLOAT, nullable=True),
        sa.Column('intraday_close_1h', sa.FLOAT, nullable=True),
        sa.Column('rsi_1h', sa.FLOAT, nullable=True),
        sa.Column('macd_1h', sa.FLOAT, nullable=True),
        sa.Column('macd_signal_1h', sa.FLOAT, nullable=True),
        sa.Column('macd_histogram_1h', sa.FLOAT, nullable=True),
        sa.Column('bb_middle_1h', sa.FLOAT, nullable=True),
        sa.Column('bb_upper_1h', sa.FLOAT, nullable=True),
        sa.Column('bb_lower_1h', sa.FLOAT, nullable=True),
        sa.Column('bb_width_1h', sa.FLOAT, nullable=True),
        sa.Column('bb_squeeze_1h', sa.VARCHAR(1), nullable=True),
        sa.Column('atr_1h', sa.FLOAT, nullable=True),
        sa.Column('atr_percent_1h', sa.FLOAT, nullable=True),
        sa.Column('vwma_20_1h', sa.FLOAT, nullable=True),
        sa.Column('hv_20_1h', sa.FLOAT, nullable=True),
        sa.Column('hv_60_1h', sa.FLOAT, nullable=True),
        sa.Column('sharpe_60_1h', sa.FLOAT, nullable=True),
        sa.Column('sharpe_126_1h', sa.FLOAT, nullable=True),
        sa.Column('intraday_close_W', sa.FLOAT, nullable=True),
        sa.Column('rsi_W', sa.FLOAT, nullable=True),
        sa.Column('macd_W', sa.FLOAT, nullable=True),
        sa.Column('macd_signal_W', sa.FLOAT, nullable=True),
        sa.Column('macd_histogram_W', sa.FLOAT, nullable=True),
        sa.Column('bb_middle_W', sa.FLOAT, nullable=True),
        sa.Column('bb_upper_W', sa.FLOAT, nullable=True),
        sa.Column('bb_lower_W', sa.FLOAT, nullable=True),
        sa.Column('bb_width_W', sa.FLOAT, nullable=True),
        sa.Column('bb_squeeze_W', sa.VARCHAR(1), nullable=True),
        sa.Column('atr_W', sa.FLOAT, nullable=True),
        sa.Column('atr_percent_W', sa.FLOAT, nullable=True),
        sa.Column('vwma_20_W', sa.FLOAT, nullable=True),
        sa.Column('hv_20_W', sa.FLOAT, nullable=True),
        sa.Column('hv_60_W', sa.FLOAT, nullable=True),
        sa.Column('sharpe_60_W', sa.FLOAT, nullable=True),
        sa.Column('sharpe_126_W', sa.FLOAT, nullable=True),
        sa.Column('intraday_close_M', sa.FLOAT, nullable=True),
        sa.Column('rsi_M', sa.FLOAT, nullable=True),
        sa.Column('macd_M', sa.FLOAT, nullable=True),
        sa.Column('macd_signal_M', sa.FLOAT, nullable=True),
        sa.Column('macd_histogram_M', sa.FLOAT, nullable=True),
        sa.Column('bb_middle_M', sa.FLOAT, nullable=True),
        sa.Column('bb_upper_M', sa.FLOAT, nullable=True),
        sa.Column('bb_lower_M', sa.FLOAT, nullable=True),
        sa.Column('bb_width_M', sa.FLOAT, nullable=True),
        sa.Column('bb_squeeze_M', sa.VARCHAR(1), nullable=True),
        sa.Column('atr_M', sa.FLOAT, nullable=True),
        sa.Column('atr_percent_M', sa.FLOAT, nullable=True),
        sa.Column('vwma_20_M', sa.FLOAT, nullable=True),
        sa.Column('hv_20_M', sa.FLOAT, nullable=True),
        sa.Column('hv_60_M', sa.FLOAT, nullable=True),
        sa.Column('sharpe_60_M', sa.FLOAT, nullable=True),
        sa.Column('sharpe_126_M', sa.FLOAT, nullable=True)
    )
    op.create_table(
        'ticker_intraday',
        sa.Column('id', sa.INTEGER, nullable=False, primary_key=True),
        sa.Column('symbol', sa.VARCHAR(32), nullable=False),
        sa.Column('timestamp', sa.DATETIME, nullable=False),
        sa.Column('interval', sa.VARCHAR(4), nullable=False),
        sa.Column('open', sa.FLOAT, nullable=False),
        sa.Column('high', sa.FLOAT, nullable=False),
        sa.Column('low', sa.FLOAT, nullable=False),
        sa.Column('close', sa.FLOAT, nullable=False),
        sa.Column('volume', sa.BIGINT, nullable=False),
        sa.Column('source', sa.VARCHAR(32), nullable=False),
        sa.Column('created_at', sa.DATETIME, nullable=False),
        sa.Column('rsi_14', sa.FLOAT, nullable=True),
        sa.Column('macd', sa.FLOAT, nullable=True),
        sa.Column('macd_signal', sa.FLOAT, nullable=True),
        sa.Column('macd_histogram', sa.FLOAT, nullable=True),
        sa.Column('bb_middle', sa.FLOAT, nullable=True),
        sa.Column('bb_upper', sa.FLOAT, nullable=True),
        sa.Column('bb_lower', sa.FLOAT, nullable=True),
        sa.Column('bb_width', sa.FLOAT, nullable=True),
        sa.Column('bb_squeeze', sa.VARCHAR(1), nullable=True),
        sa.Column('atr_14', sa.FLOAT, nullable=True),
        sa.Column('atr_percent', sa.FLOAT, nullable=True),
        sa.Column('vwma_20', sa.FLOAT, nullable=True),
        sa.Column('hv_20', sa.FLOAT, nullable=True),
        sa.Column('hv_60', sa.FLOAT, nullable=True),
        sa.Column('sharpe_60', sa.FLOAT, nullable=True),
        sa.Column('sharpe_126', sa.FLOAT, nullable=True),
        sa.Column('indicators_updated_at', sa.DATETIME, nullable=True)
    )
    op.create_table(
        'users',
        sa.Column('id', sa.INTEGER, nullable=False, primary_key=True),
        sa.Column('username', sa.VARCHAR(64), nullable=False),
        sa.Column('hashed_password', sa.VARCHAR(128), nullable=False),
        sa.Column('is_admin', sa.BOOLEAN, nullable=False, server_default=sa.text('False')),
        sa.Column('created_at', sa.DATETIME, nullable=False)
    )
    op.create_table(
        'watchlists',
        sa.Column('id', sa.INTEGER, nullable=False, primary_key=True),
        sa.Column('user_id', sa.INTEGER, nullable=False, server_default=sa.text('1')),
        sa.Column('name', sa.VARCHAR(32), nullable=False),
        sa.Column('created_at', sa.DATETIME, nullable=False)
    )
    op.create_table(
        'watchlist_items',
        sa.Column('id', sa.INTEGER, nullable=False, primary_key=True),
        sa.Column('watchlist_id', sa.INTEGER, nullable=False),
        sa.Column('symbol', sa.VARCHAR(32), nullable=False),
        sa.Column('exchange', sa.VARCHAR(16), nullable=False),
        sa.Column('created_at', sa.DATETIME, nullable=False)
    )
    op.create_table(
        'jobs',
        sa.Column('id', sa.INTEGER, nullable=False, primary_key=True),
        sa.Column('job_key', sa.VARCHAR(64), nullable=False),
        sa.Column('name', sa.VARCHAR(64), nullable=False),
        sa.Column('description', sa.VARCHAR(256), nullable=False),
        sa.Column('category', sa.VARCHAR(32), nullable=False),
        sa.Column('schedule_type', sa.VARCHAR(16), nullable=False),
        sa.Column('interval_seconds', sa.INTEGER, nullable=True),
        sa.Column('cron_expression', sa.VARCHAR(32), nullable=True),
        sa.Column('last_triggered_at', sa.DATETIME, nullable=True),
        sa.Column('last_completed_at', sa.DATETIME, nullable=True),
        sa.Column('next_trigger_at', sa.DATETIME, nullable=True),
        sa.Column('last_error', sa.VARCHAR(512), nullable=True),
        sa.Column('status', sa.VARCHAR(32), nullable=False, server_default=sa.text('idle')),
        sa.Column('progress_percent', sa.INTEGER, nullable=False, server_default=sa.text('0')),
        sa.Column('progress_message', sa.VARCHAR(128), nullable=True),
        sa.Column('is_enabled', sa.BOOLEAN, nullable=False, server_default=sa.text('True')),
        sa.Column('is_manual_only', sa.BOOLEAN, nullable=False, server_default=sa.text('False')),
        sa.Column('created_at', sa.DATETIME, nullable=False),
        sa.Column('updated_at', sa.DATETIME, nullable=False)
    )
    op.create_table(
        'system_config',
        sa.Column('key', sa.VARCHAR(64), nullable=False, primary_key=True),
        sa.Column('value', sa.VARCHAR(512), nullable=True),
        sa.Column('updated_at', sa.DATETIME, nullable=False)
    )



# Indexes
    op.create_index('ix_chat_messages_session_id', 'chat_messages', ['session_id'])
    op.create_index('ix_corporate_filings_symbol', 'corporate_filings', ['symbol'])
    op.create_index('ix_market_categories_type_slug', 'market_categories', ['category_type', 'slug'])
    op.create_index('ix_market_category_stocks_symbol', 'market_category_stocks', ['symbol'])
    op.create_index('ix_news_articles_company_symbol', 'news_articles', ['company_symbol'])
    op.create_index('ix_news_articles_sentiment', 'news_articles', ['sentiment'])
    op.create_index('ix_news_articles_url', 'news_articles', ['url'])
    op.create_index('ix_news_articles_publish_date', 'news_articles', ['publish_date'])
    op.create_index('ix_news_articles_threat_level', 'news_articles', ['threat_level'])
    op.create_index('ix_news_articles_source_publish', 'news_articles', ['source', 'publish_date'])
    op.create_index('ix_news_articles_source', 'news_articles', ['source'])
    op.create_index('ix_news_articles_language', 'news_articles', ['language'])
    op.create_index('ix_notifications_triggered_date', 'notifications', ['triggered_date'])
    op.create_index('ix_notifications_watchlist_unread', 'notifications', ['watchlist_id', 'is_read'])
    op.create_index('ix_global_notifications_unread', 'global_notifications', ['is_read'])
    op.create_index('ix_global_notifications_symbol', 'global_notifications', ['symbol'])
    op.create_index('ix_global_notifications_triggered_date', 'global_notifications', ['triggered_date'])
    op.create_index('ix_stock_universe_symbol', 'stock_universe', ['symbol'])
    op.create_index('ix_ticker_daily_symbol', 'ticker_daily', ['symbol'])
    op.create_index('ix_ticker_daily_date', 'ticker_daily', ['date'])
    op.create_index('ix_ticker_scores_compute_date', 'ticker_scores', ['compute_date'])
    op.create_index('ix_ticker_scores_symbol', 'ticker_scores', ['symbol'])
    op.create_index('ix_ticker_screener_snapshot_last_date', 'ticker_screener_snapshot', ['last_date'])
    op.create_index('ix_ticker_screener_snapshot_compute_date', 'ticker_screener_snapshot', ['compute_date'])
    op.create_index('ix_snapshot_sector_pe', 'ticker_screener_snapshot', ['sector', 'pe'])
    op.create_index('ix_ticker_screener_snapshot_sector', 'ticker_screener_snapshot', ['sector'])
    op.create_index('ix_snapshot_compute_date', 'ticker_screener_snapshot', ['compute_date'])
    op.create_index('ix_ticker_intraday_symbol_interval', 'ticker_intraday', ['symbol', 'interval'])
    op.create_index('ix_ticker_intraday_symbol', 'ticker_intraday', ['symbol'])
    op.create_index('ix_ticker_intraday_timestamp', 'ticker_intraday', ['timestamp'])
    op.create_index('ix_users_username', 'users', ['username'], unique=True)
    op.create_index('ix_jobs_name', 'jobs', ['name'])
    op.create_index('ix_jobs_next_trigger_at', 'jobs', ['next_trigger_at'])
    op.create_index('ix_jobs_status', 'jobs', ['status'])
    op.create_index('ix_system_config_key', 'system_config', ['key'])

def downgrade() -> None:

    op.drop_index('ix_chat_messages_session_id', table_name='chat_messages')
    op.drop_index('ix_corporate_filings_symbol', table_name='corporate_filings')
    op.drop_index('ix_market_categories_type_slug', table_name='market_categories')
    op.drop_index('ix_market_category_stocks_symbol', table_name='market_category_stocks')
    op.drop_index('ix_news_articles_company_symbol', table_name='news_articles')
    op.drop_index('ix_news_articles_sentiment', table_name='news_articles')
    op.drop_index('ix_news_articles_url', table_name='news_articles')
    op.drop_index('ix_news_articles_publish_date', table_name='news_articles')
    op.drop_index('ix_news_articles_threat_level', table_name='news_articles')
    op.drop_index('ix_news_articles_source_publish', table_name='news_articles')
    op.drop_index('ix_news_articles_source', table_name='news_articles')
    op.drop_index('ix_news_articles_language', table_name='news_articles')
    op.drop_index('ix_notifications_triggered_date', table_name='notifications')
    op.drop_index('ix_notifications_watchlist_unread', table_name='notifications')
    op.drop_index('ix_global_notifications_unread', table_name='global_notifications')
    op.drop_index('ix_global_notifications_symbol', table_name='global_notifications')
    op.drop_index('ix_global_notifications_triggered_date', table_name='global_notifications')
    op.drop_index('ix_stock_universe_symbol', table_name='stock_universe')
    op.drop_index('ix_ticker_daily_symbol', table_name='ticker_daily')
    op.drop_index('ix_ticker_daily_date', table_name='ticker_daily')
    op.drop_index('ix_ticker_scores_compute_date', table_name='ticker_scores')
    op.drop_index('ix_ticker_scores_symbol', table_name='ticker_scores')
    op.drop_index('ix_ticker_screener_snapshot_last_date', table_name='ticker_screener_snapshot')
    op.drop_index('ix_ticker_screener_snapshot_compute_date', table_name='ticker_screener_snapshot')
    op.drop_index('ix_snapshot_sector_pe', table_name='ticker_screener_snapshot')
    op.drop_index('ix_ticker_screener_snapshot_sector', table_name='ticker_screener_snapshot')
    op.drop_index('ix_snapshot_compute_date', table_name='ticker_screener_snapshot')
    op.drop_index('ix_ticker_intraday_symbol_interval', table_name='ticker_intraday')
    op.drop_index('ix_ticker_intraday_symbol', table_name='ticker_intraday')
    op.drop_index('ix_ticker_intraday_timestamp', table_name='ticker_intraday')
    op.drop_index('ix_users_username', table_name='users')
    op.drop_index('ix_jobs_name', table_name='jobs')
    op.drop_index('ix_jobs_next_trigger_at', table_name='jobs')
    op.drop_index('ix_jobs_status', table_name='jobs')
    op.drop_index('ix_system_config_key', table_name='system_config')
    op.drop_table('chat_sessions')
    op.drop_table('chat_messages')
    op.drop_table('corporate_filings')
    op.drop_table('market_categories')
    op.drop_table('market_category_stocks')
    op.drop_table('news_articles')
    op.drop_table('notifications')
    op.drop_table('global_notifications')
    op.drop_table('stock_universe')
    op.drop_table('ticker_daily')
    op.drop_table('ticker_scores')
    op.drop_table('ticker_screener_snapshot')
    op.drop_table('ticker_intraday')
    op.drop_table('users')
    op.drop_table('watchlists')
    op.drop_table('watchlist_items')
    op.drop_table('jobs')
    op.drop_table('system_config')
