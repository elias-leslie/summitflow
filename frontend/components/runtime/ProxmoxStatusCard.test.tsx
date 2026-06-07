import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ProxmoxStatusCard } from './ProxmoxStatusCard'

const queryMocks = vi.hoisted(() => ({
  useQuery: vi.fn(),
}))

vi.mock('@tanstack/react-query', () => ({
  useQuery: queryMocks.useQuery,
}))

describe('ProxmoxStatusCard', () => {
  it('renders a collapsed summary when Proxmox is not configured', () => {
    queryMocks.useQuery.mockReturnValue({
      data: {
        configured: false,
        reachable: false,
        api_url: null,
        error:
          'Set PROXMOX_API_URL, PROXMOX_TOKEN_ID, and PROXMOX_TOKEN_SECRET to enable Proxmox status.',
        nodes: [],
        guests: [],
      },
      error: undefined,
      isLoading: false,
    })

    render(<ProxmoxStatusCard />)

    expect(screen.getByText('Proxmox')).toBeInTheDocument()
    expect(screen.getByText('Not configured')).toBeInTheDocument()
  })

  it('renders node and guest status when expanded', () => {
    queryMocks.useQuery.mockReturnValue({
      data: {
        configured: true,
        reachable: true,
        api_url: 'https://192.0.2.33:8006',
        error: null,
        nodes: [
          {
            node: 'davion-gem',
            status: 'online',
            cpu_percent: 12.5,
            memory_used_bytes: 8 * 1024 * 1024 * 1024,
            memory_total_bytes: 16 * 1024 * 1024 * 1024,
            uptime_seconds: 12_345,
          },
        ],
        guests: [
          {
            vmid: 100,
            name: 'browser-test-vm',
            node: 'davion-gem',
            type: 'qemu',
            status: 'running',
            cpu_percent: 25,
            memory_used_bytes: 4 * 1024 * 1024 * 1024,
            memory_total_bytes: 8 * 1024 * 1024 * 1024,
            uptime_seconds: 5_678,
            tags: ['test', 'browser'],
          },
        ],
      },
      error: undefined,
      isLoading: false,
    })

    render(<ProxmoxStatusCard />)

    // Summary visible in collapsed state
    expect(
      screen.getByText('1/1 nodes online, 1/1 guests running'),
    ).toBeInTheDocument()

    // Expand by clicking
    fireEvent.click(screen.getByText('Proxmox'))

    expect(screen.getByText('davion-gem')).toBeInTheDocument()
    expect(screen.getByText('browser-test-vm')).toBeInTheDocument()
    expect(screen.getByText('Tags: test, browser')).toBeInTheDocument()
  })
})
