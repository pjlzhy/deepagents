import React from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { ConfigProvider } from '@arco-design/web-react';
import '@arco-design/web-react/es/_util/react-19-adapter';
import '@arco-design/web-react/dist/css/arco.css';
import zhCN from '@arco-design/web-react/es/locale/zh-CN';
import 'uno.css';
import '@unocss/reset/tailwind.css';
import '@/styles/theme.css';
import App from '@/app/App';

const root = createRoot(document.getElementById('root')!);

root.render(
  <React.StrictMode>
    <ConfigProvider locale={zhCN} theme={{ primaryColor: '#00f0ff' }}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </ConfigProvider>
  </React.StrictMode>,
);

