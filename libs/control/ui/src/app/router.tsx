import type { ReactNode } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import OverviewPage from '@/pages/overview';
import ModelsPage from '@/pages/registry/ModelsPage';
import SkillsPage from '@/pages/registry/SkillsPage';
import MCPsPage from '@/pages/registry/MCPsPage';
import SandboxesPage from '@/pages/registry/SandboxesPage';
import AgentsPage from '@/pages/registry/AgentsPage';
import ChatWorkspacePage from '@/pages/chat';

function StretchPage(props: { children: ReactNode }) {
  return <div className='flex min-h-0 flex-1 flex-col overflow-hidden'>{props.children}</div>;
}

export default function AppRouter() {
  return (
    <Routes>
      <Route path='/' element={<Navigate to='/overview' replace />} />
      <Route path='/overview' element={<OverviewPage />} />
      <Route path='/registry/models' element={<ModelsPage />} />
      <Route path='/registry/skills' element={<SkillsPage />} />
      <Route path='/registry/mcps' element={<MCPsPage />} />
      <Route path='/registry/sandboxes' element={<SandboxesPage />} />
      <Route path='/registry/agents' element={<AgentsPage />} />
      <Route path='/registry/agents/new' element={<AgentsPage />} />
      <Route path='/registry/agents/:agentName' element={<AgentsPage />} />
      <Route
        path='/chat'
        element={
          <StretchPage>
            <ChatWorkspacePage />
          </StretchPage>
        }
      />
      <Route
        path='/chat/:agentName'
        element={
          <StretchPage>
            <ChatWorkspacePage />
          </StretchPage>
        }
      />
      <Route
        path='/chat/:agentName/:threadId'
        element={
          <StretchPage>
            <ChatWorkspacePage />
          </StretchPage>
        }
      />
      <Route path='*' element={<Navigate to='/overview' replace />} />
    </Routes>
  );
}
