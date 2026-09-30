-- Practical Python, shell, JSON/YAML, and JavaScript/TypeScript support.
return {
  { import = "lazyvim.plugins.extras.lang.python" },
  { import = "lazyvim.plugins.extras.lang.json" },
  { import = "lazyvim.plugins.extras.lang.yaml" },
  { import = "lazyvim.plugins.extras.lang.typescript" },
  {
    "neovim/nvim-lspconfig",
    opts = function(_, opts)
      opts.servers = opts.servers or {}
      opts.servers.bashls = opts.servers.bashls or {}
      for _, server in pairs(opts.servers) do
        if type(server) == "table" then server.mason = false end
      end
    end,
  },
  {
    "nvim-treesitter/nvim-treesitter",
    opts = function(_, opts)
      opts.ensure_installed = {}
      opts.auto_install = false
    end,
  },
  {
    "mason-org/mason.nvim",
    opts = function(_, opts)
      opts.install_root_dir = vim.fn.expand("~/.local/share/terminal-kit/nvim/mason")
      opts.PATH = "prepend"
      opts.ensure_installed = {}
    end,
  },
}
