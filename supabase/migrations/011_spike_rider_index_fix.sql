-- Fix auction_series unique index: should be unique per module, not globally per (handle, title_filter).
-- Otherwise a second Spike Rider module tracking the same handle/filter (e.g. a 30-day variant)
-- would fail on insert.
drop index if exists idx_auction_series_handle_title;
create unique index if not exists idx_auction_series_module_handle_title
  on auction_series(module_id, handle, title_filter);
