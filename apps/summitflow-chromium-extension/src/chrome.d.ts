declare namespace chrome {
  namespace action {
    const onClicked: {
      addListener(callback: (tab: tabs.Tab) => void): void
    }
  }

  namespace runtime {
    const lastError: { message?: string } | undefined
    const onMessage: {
      addListener(
        callback: (
          message: unknown,
          sender: MessageSender,
          sendResponse: (response?: unknown) => void,
        ) => boolean | void,
      ): void
    }
    function sendMessage(message: unknown): void
  }

  namespace scripting {
    function executeScript(
      injection: {
        target: { tabId: number }
        files: string[]
      },
      callback?: () => void,
    ): void
  }

  namespace storage {
    const session: StorageArea

    interface StorageArea {
      get(keys?: string | string[] | Record<string, unknown> | null): Promise<Record<string, unknown>>
      set(items: Record<string, unknown>): Promise<void>
      remove(keys: string | string[]): Promise<void>
    }
  }

  namespace tabs {
    interface Tab {
      id?: number
      url?: string
    }

    function sendMessage(tabId: number, message: unknown, callback?: () => void): void
  }

  interface MessageSender {
    tab?: tabs.Tab
  }
}
