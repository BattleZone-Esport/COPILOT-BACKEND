
{ pkgs, ... }: {
  # Which nixpkgs channel to use.
  channel = "stable-23.11"; # or "unstable"

  # Use https://search.nixos.org/packages to find packages
  packages = [
    pkgs.python311
    pkgs.python311Packages.pip
  ];

  # Sets environment variables in the workspace
  env = {};

  # Defines shell aliases
  # shellAliases = {
  #   "hello" = "echo 'Hello from Nix!'";
  # };

  # Defines a script to run when the workspace starts
  # startup = {
  #   "example" = "echo 'This is an example startup script.'";
  # };
}
