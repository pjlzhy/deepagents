import { Button } from '@arco-design/web-react';
import { BUILDER_STEPS, type StepCompletion } from '@/features/agent-builder/builderForm';
import { REGISTRY_ICONS } from '@/pages/registry/registryIcons';

type BuilderHudBarProps = {
  completion: StepCompletion[];
  onStepChange: (step: number) => void;
  saving: boolean;
  onSave: () => void;
  onBuild: () => void;
  isEdit: boolean;
};

export default function BuilderHudBar(props: BuilderHudBarProps) {
  return (
    <div className='builder-hud'>
      <div className='flex items-center justify-between gap-12px'>
        {/* Summary pills */}
        <div className='flex flex-1 flex-wrap items-center gap-6px'>
          {BUILDER_STEPS.map((step, index) => {
            const comp = props.completion[index];
            const isComplete = comp?.complete ?? false;
            const IconComp = REGISTRY_ICONS[step.iconKey];
            return (
              <div
                key={step.key}
                className={`builder-hud-pill ${isComplete ? 'builder-hud-pill--complete' : ''}`}
                style={{
                  '--pill-accent': step.accent,
                  '--pill-glow': step.glow,
                  color: isComplete ? step.accent : 'var(--control-subtle)',
                } as React.CSSProperties}
                onClick={() => props.onStepChange(index)}
              >
                <IconComp size={14} fill={[isComplete ? step.accent : 'var(--control-subtle)']} />
                <span className='text-[var(--control-subtle)]'>
                  {comp?.summary ?? '—'}
                </span>
              </div>
            );
          })}
        </div>

        {/* Actions */}
        <div className='flex shrink-0 items-center gap-8px'>
          <Button loading={props.saving} onClick={props.onSave}>
            Save
          </Button>
          <Button type='primary' loading={props.saving} onClick={props.onBuild}>
            Build
          </Button>
        </div>
      </div>
    </div>
  );
}
