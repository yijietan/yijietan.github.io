-- Appends the email signup box (_includes/subscribe.html) to the end of the page.
-- Applied to every post via posts/_metadata.yml, and to the home page.
-- On posts (metadata `post-comments: true`), then adds the likes and comments
-- block (_includes/comments.html).

local function read_file(path)
  local f = io.open(path, "r")
  if not f then return nil end
  local s = f:read("a")
  f:close()
  return s
end

function Pandoc(doc)
  if not quarto.doc.is_format("html") then return doc end
  local here = PANDOC_SCRIPT_FILE:match("(.*[/\\])") or ""
  local html = read_file(here .. "../_includes/subscribe.html")
  if html then
    doc.blocks:insert(pandoc.RawBlock("html", html))
  end
  if doc.meta["post-comments"] then
    local comments = read_file(here .. "../_includes/comments.html")
    if comments then
      doc.blocks:insert(pandoc.RawBlock("html", comments))
    end
  end
  return doc
end
