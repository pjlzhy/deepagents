import { BUILDER_STEPS, type StepCompletion } from '@/features/agent-builder/builderForm';
import { REGISTRY_ICONS } from '@/pages/registry/registryIcons';

type BuilderStepNavProps = {
  currentStep: number;
  completion: StepCompletion[];
  onStepChange: (step: number) => void;
};

export default function BuilderStepNav(props: BuilderStepNavProps) {
  return (
    <div className='builder-step-nav py-16px'>
      {BUILDER_STEPS.map((step, index) => {
        const isComplete = props.completion[index]?.complete ?? false;
        const isCurrent = index === props.currentStep;
        const IconComp = REGISTRY_ICONS[step.iconKey];

        return (
          <div key={step.key} className='flex flex-col items-center'>
            {index > 0 && (
              <div
                className={`builder-step-line ${
                  props.completion[index - 1]?.complete ? 'builder-step-line--active' : ''
                }`}
                style={{
                  '--step-accent': BUILDER_STEPS[index - 1].accent,
                } as React.CSSProperties}
              />
            )}
            <div
              className={`builder-step-node ${isComplete ? 'builder-step-node--complete' : ''} ${
                isCurrent ? 'builder-step-node--current' : ''
              }`}
              style={{
                '--step-accent': step.accent,
                '--step-glow': step.glow,
              } as React.CSSProperties}
              onClick={() => props.onStepChange(index)}
            >
              <IconComp
                size={20}
                fill={[isComplete || isCurrent ? step.accent : 'var(--control-subtle)']}
              />
            </div>
            <div
              className={`builder-step-label ${isCurrent ? 'builder-step-label--active' : ''}`}
              style={isCurrent ? { color: step.accent } : undefined}
            >
              {step.label}
            </div>
          </div>
        );
      })}
    </div>
  );
}
