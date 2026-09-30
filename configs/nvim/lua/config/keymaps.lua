-- Preserve LazyVim's Space leader and discovery defaults.
vim.g.mapleader = " "
vim.g.maplocalleader = "\\"
vim.keymap.set("n", "<leader>fc", function()
  Snacks.picker.files({ cwd = vim.fn.expand("~/.config/terminal-kit") })
end, { desc = "Find Terminal Kit config file" })
