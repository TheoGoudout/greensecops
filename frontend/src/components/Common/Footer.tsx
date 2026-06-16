export function Footer() {
  const currentYear = new Date().getFullYear()

  return (
    <footer className="border-t py-4 px-6">
      <p className="text-muted-foreground text-sm text-center sm:text-left">
        GreenSecOps - {currentYear}
      </p>
    </footer>
  )
}
