export function canStartGame(playerCount: number): boolean {
  return (
    Number.isInteger(playerCount) &&
    playerCount >= 4 &&
    playerCount <= 6
  )
}
