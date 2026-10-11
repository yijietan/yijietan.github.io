-- Let the browser size table columns to their content.
-- Pandoc fixes column widths from the header separator dashes whenever a table's
-- source lines are long, which leaves short columns too wide and long ones cramped.

function Table(tbl)
  for i, spec in ipairs(tbl.colspecs) do
    tbl.colspecs[i] = { spec[1], pandoc.ColWidthDefault }
  end
  return tbl
end
