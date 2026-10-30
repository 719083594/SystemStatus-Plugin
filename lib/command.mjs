// The only command. Shared by the TRSS adapter and the manifest test so they cannot drift apart.
// TRSS turns a leading "/" into "#" before matching (bot.yaml "/→#").
export const COMMAND_REG = /^#\s*系统状态\s*$/
