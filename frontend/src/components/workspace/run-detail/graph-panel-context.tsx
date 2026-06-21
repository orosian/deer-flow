"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

interface GraphPanelContextType {
  open: boolean;
  setOpen: (open: boolean) => void;
  toggle: () => void;
}

const GraphPanelContext = createContext<GraphPanelContextType | undefined>(
  undefined,
);

interface GraphPanelProviderProps {
  children: ReactNode;
}

export function GraphPanelProvider({ children }: GraphPanelProviderProps) {
  const [open, setOpenState] = useState(false);

  const setOpen = useCallback((next: boolean) => {
    setOpenState(next);
  }, []);

  const toggle = useCallback(() => {
    setOpenState((current) => !current);
  }, []);

  const value = useMemo<GraphPanelContextType>(
    () => ({ open, setOpen, toggle }),
    [open, setOpen, toggle],
  );

  return (
    <GraphPanelContext.Provider value={value}>
      {children}
    </GraphPanelContext.Provider>
  );
}

export function useGraphPanel() {
  const context = useContext(GraphPanelContext);
  if (context === undefined) {
    throw new Error("useGraphPanel must be used within a GraphPanelProvider");
  }
  return context;
}
