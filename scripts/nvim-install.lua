-- Synchronous installation acceptance; never run by ordinary editor startup.
local ok, err = pcall(function()
  local check_only = vim.env.TERMINAL_KIT_NVIM_CHECK == "1"
  local config = require("lazy.core.config")
  assert(config.plugins.LazyVim, "LazyVim was not loaded")
  require("lazy").load({ plugins = { "mason.nvim", "nvim-treesitter" } })
  vim.env.PATH = vim.fn.fnamemodify(vim.env.TERMINAL_KIT_TREE_SITTER, ":h") .. ":" .. vim.env.PATH
  local registry = require("mason-registry")
  if not check_only then
    local refreshed = false
    registry.refresh(function() refreshed = true end)
    assert(vim.wait(120000, function() return refreshed end, 100), "Mason registry refresh timed out")
  end
  local names = { "pyright", "ruff", "bash-language-server", "json-lsp", "yaml-language-server", "vtsls", "prettier", "shfmt", "shellcheck", "stylua" }
  local pending = #names
  local failures = {}
  for _, name in ipairs(names) do
    local package = registry.get_package(name)
    if package:is_installed() then
      pending = pending - 1
    else
      assert(not check_only, name .. " is missing")
      package:once("install:success", function() pending = pending - 1 end)
      package:once("install:failed", function() table.insert(failures, name); pending = pending - 1 end)
      if not package:is_installing() then package:install() end
    end
  end
  assert(vim.wait(900000, function() return pending == 0 end, 100), "Mason installation timed out")
  assert(#failures == 0, "Mason failed: " .. table.concat(failures, ", "))
  for _, name in ipairs(names) do assert(registry.get_package(name):is_installed(), name .. " missing") end
  local parsers = { "bash", "json", "json5", "yaml", "python", "javascript", "typescript", "tsx" }
  if not check_only then
    local finished = require("nvim-treesitter.install").install(parsers, { summary = true }):wait(600000)
    assert(finished ~= false, "Treesitter parser compilation failed; inspect messages above")
  end
  for _, parser in ipairs(parsers) do
    assert(#vim.api.nvim_get_runtime_file("parser/" .. parser .. ".so", false) > 0, parser .. " parser missing")
  end
  assert(vim.g.mapleader == " ", "Leader key changed unexpectedly")
end)
if not ok then
  io.stderr:write("TERMINAL_KIT_NVIM_FAILED: " .. tostring(err) .. "\n")
  vim.cmd("cquit 1")
else
  io.stdout:write("TERMINAL_KIT_NVIM_OK\n")
end
