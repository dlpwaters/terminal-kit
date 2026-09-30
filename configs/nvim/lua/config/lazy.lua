-- This setup is seeded by terminal-kit install; startup never clones or updates.
local plugin_root = vim.fn.expand("~/.local/share/terminal-kit/nvim/lazy")
local lazy_path = plugin_root .. "/lazy.nvim"
if vim.fn.isdirectory(lazy_path) == 0 then
  vim.api.nvim_echo({
    { "terminal-kit: Neovim plugins are not installed. Run terminal-kit install.\n", "ErrorMsg" },
  }, true, {})
  vim.cmd("cquit 1")
  return
end
vim.opt.rtp:prepend(lazy_path)

local lockfile = vim.env.TERMINAL_KIT_LOCKFILE or vim.fn.expand("~/.local/state/terminal-kit/nvim-lazy-lock.json")
local local_specs = package.loaded["terminal_kit_local_specs"] or {}
local specs = {
  { "LazyVim/LazyVim", import = "lazyvim.plugins" },
  { import = "plugins" },
}
for _, spec in ipairs(local_specs) do table.insert(specs, spec) end

require("lazy").setup({
  spec = specs,
  root = plugin_root,
  lockfile = lockfile,
  defaults = { lazy = false, version = false },
  install = { missing = vim.env.TERMINAL_KIT_INSTALL == "1", colorscheme = { "tokyonight", "habamax" } },
  checker = { enabled = false },
  change_detection = { enabled = false },
  performance = {
    rtp = { paths = { vim.fn.expand("~/.config/terminal-kit/nvim") }, disabled_plugins = { "gzip", "tarPlugin", "tohtml", "tutor", "zipPlugin" } },
  },
})
