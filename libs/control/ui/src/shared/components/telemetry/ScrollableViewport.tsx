export default function ScrollableViewport(props: {
  viewportRef?: React.MutableRefObject<HTMLDivElement | null>;
  viewportClassName?: string;
  children: React.ReactNode;
}) {
  return (
    <div
      ref={(node) => {
        if (props.viewportRef) props.viewportRef.current = node;
      }}
      className={`control-scroll control-scroll-strong min-h-0 h-full overflow-y-scroll overflow-x-hidden ${props.viewportClassName ?? ''}`}
    >
      <div className='min-h-full'>
        {props.children}
      </div>
    </div>
  );
}
