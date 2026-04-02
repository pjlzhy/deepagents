import { useCallback, useEffect, useRef, useState } from 'react';
import { Button, Input } from '@arco-design/web-react';
import { Add, CloseOne } from '@icon-park/react';

type Row = { id: number; key: string; value: string };

export type KeyValueEditorProps = {
  value?: Record<string, string>;
  onChange?: (value: Record<string, string>) => void;
  keyPlaceholder?: string;
  valuePlaceholder?: string;
  disabled?: boolean;
};

let nextId = 1;

function recordToRows(record?: Record<string, string>): Row[] {
  if (!record || Object.keys(record).length === 0) return [];
  return Object.entries(record).map(([key, value]) => ({ id: nextId++, key, value }));
}

function rowsToRecord(rows: Row[]): Record<string, string> {
  const result: Record<string, string> = {};
  for (const row of rows) {
    const k = row.key.trim();
    if (k) result[k] = row.value;
  }
  return result;
}

export default function KeyValueEditor(props: KeyValueEditorProps) {
  const { value, onChange, keyPlaceholder = 'Key', valuePlaceholder = 'Value', disabled } = props;
  const [rows, setRows] = useState<Row[]>(() => recordToRows(value));
  const lastEmittedRef = useRef<string>('');

  useEffect(() => {
    const incoming = JSON.stringify(value ?? {});
    if (incoming !== lastEmittedRef.current) {
      setRows(recordToRows(value));
      lastEmittedRef.current = incoming;
    }
  }, [value]);

  const emit = useCallback(
    (nextRows: Row[]) => {
      setRows(nextRows);
      const record = rowsToRecord(nextRows);
      lastEmittedRef.current = JSON.stringify(record);
      onChange?.(record);
    },
    [onChange],
  );

  function addRow() {
    emit([...rows, { id: nextId++, key: '', value: '' }]);
  }

  function removeRow(id: number) {
    emit(rows.filter((r) => r.id !== id));
  }

  function updateRow(id: number, field: 'key' | 'value', val: string) {
    emit(rows.map((r) => (r.id === id ? { ...r, [field]: val } : r)));
  }

  return (
    <div className='flex flex-col gap-6px'>
      {rows.map((row) => (
        <div key={row.id} className='flex items-center gap-6px'>
          <Input
            className='flex-1'
            size='small'
            placeholder={keyPlaceholder}
            value={row.key}
            disabled={disabled}
            onChange={(val) => updateRow(row.id, 'key', val)}
          />
          <Input
            className='flex-[2]'
            size='small'
            placeholder={valuePlaceholder}
            value={row.value}
            disabled={disabled}
            onChange={(val) => updateRow(row.id, 'value', val)}
          />
          <Button
            size='mini'
            type='text'
            icon={<CloseOne theme='outline' size='14' fill='currentColor' />}
            disabled={disabled}
            className='shrink-0'
            onClick={() => removeRow(row.id)}
          />
        </div>
      ))}
      <Button
        size='small'
        type='text'
        icon={<Add theme='outline' size='14' fill='currentColor' />}
        disabled={disabled}
        className='self-start'
        onClick={addRow}
      >
        Add
      </Button>
    </div>
  );
}
