-- Terminal Kit adapts the Omarchy LazyVim package into a portable, separate config.
-- Keep the normal ~/.config/nvim entry as a small launcher into this directory.
local managed = vim.fn.expand("~/.config/terminal-kit/nvim")
local previous_config = vim.fn.stdpath("config")
if previous_config ~= managed then
  -- Keep old files intact while preventing their Omarchy-specific plugin specs
  -- from being imported alongside the managed config.
  vim.opt.rtp:remove(previous_config)
end
vim.opt.rtp:prepend(managed)
vim.g.lazyvim_json = managed .. "/lazyvim.json"

local local_root = vim.fn.expand("~/.config/terminal-kit/local")
local local_file = local_root .. "/nvim.lua"
if vim.fn.filereadable(local_file) == 1 then
  local ok, specs = pcall(dofile, local_file)
  if ok and type(specs) == "table" then
    package.loaded["terminal_kit_local_specs"] = specs
  elseif not ok then
    vim.notify("terminal-kit local nvim.lua: " .. tostring(specs), vim.log.levels.ERROR)
  end
end

local plugin_dir = local_root .. "/nvim/plugins"
local plugin_files = vim.fn.glob(plugin_dir .. "/*.lua", false, true)
table.sort(plugin_files)
local local_specs = package.loaded["terminal_kit_local_specs"] or {}
for _, path in ipairs(plugin_files) do
  local ok, spec = pcall(dofile, path)
  if ok then
    if type(spec) == "table" then
      table.insert(local_specs, spec)
    elseif type(spec) == "function" then
      local produced_ok, produced = pcall(spec)
      if produced_ok and type(produced) == "table" then table.insert(local_specs, produced) end
    end
  else
    vim.notify("terminal-kit local plugin " .. path .. ": " .. tostring(spec), vim.log.levels.ERROR)
  end
end
package.loaded["terminal_kit_local_specs"] = local_specs

require("config.lazy")
