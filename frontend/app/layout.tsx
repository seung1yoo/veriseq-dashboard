import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'VeriSeq Dashboard',
  description: 'Self-hosted VeriSeq results, QC, review, and exports.',
};

export default function RootLayout({ children }: Readonly<{children: React.ReactNode}>) {
  return <html lang="en"><body className="antialiased">{children}</body></html>;
}
