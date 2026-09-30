vim.opt.relativenumber = false
vim.g.autoformat = false
vim.opt.clipboard = "unnamedplus"
vim.g.clipboard = {
  name = "terminal-kit",
  copy = {
    ["+"] = { "terminal-kit", "clipboard", "copy" },
    ["*"] = { "terminal-kit", "clipboard", "copy" },
  },
  paste = {
    ["+"] = { "terminal-kit", "clipboard", "paste" },
    ["*"] = { "terminal-kit", "clipboard", "paste" },
  },
  cache_enabled = 0,
}
