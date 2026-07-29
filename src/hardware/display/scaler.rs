use core::usize;

pub struct ScreenScaler<
    const IN_HEIGHT: usize,
    const IN_WIDTH: usize,
    const OUT_HEIGHT: usize,
    const OUT_WIDTH: usize,
> {
    width_ceil_calcs: [u16; IN_WIDTH],
    height_ceil_calcs: [u16; IN_HEIGHT],
}

impl<
        const IN_HEIGHT: usize,
        const IN_WIDTH: usize,
        const OUT_HEIGHT: usize,
        const OUT_WIDTH: usize,
    > ScreenScaler<IN_HEIGHT, IN_WIDTH, OUT_HEIGHT, OUT_WIDTH>
{
    pub fn new() -> Self {
        let width_ceil_calcs =
            generate_scaling_ratio::<IN_WIDTH>(OUT_WIDTH as f32 / IN_WIDTH as f32);
        let height_ceil_calcs =
            generate_scaling_ratio::<IN_HEIGHT>(OUT_HEIGHT as f32 / IN_HEIGHT as f32);

        Self {
            width_ceil_calcs,
            height_ceil_calcs,
        }
    }

    #[inline(always)]
    pub fn scale_iterator<'a, T, I>(&'a self, iterator: I) -> impl Iterator<Item = T> + 'a
    where
        I: Iterator<Item = T> + 'a,
        T: Default + Copy + 'a,
    {
        ScalerIterator::<'a, T, IN_HEIGHT, IN_WIDTH, OUT_HEIGHT, OUT_WIDTH, I>::new(
            iterator,
            &self.width_ceil_calcs,
            &self.height_ceil_calcs,
        )
    }
}

struct ScalerIterator<
    'a,
    T,
    const IN_HEIGHT: usize,
    const IN_WIDTH: usize,
    const OUT_HEIGHT: usize,
    const OUT_WIDTH: usize,
    I: Iterator<Item = T>,
> {
    iterator: I,
    input_current_scan_line: u16,
    output_current_scan_line: u16,
    scaled_scan_line_buffer: [T; OUT_WIDTH],
    width_ceil_calcs: &'a [u16],
    height_ceil_calcs: &'a [u16],
    scaled_line_buffer_repeat: u16,
    current_scaled_line_index: u16,
}

impl<
        'a,
        T,
        const IN_HEIGHT: usize,
        const IN_WIDTH: usize,
        const OUT_HEIGHT: usize,
        const OUT_WIDTH: usize,
        I,
    > ScalerIterator<'a, T, IN_HEIGHT, IN_WIDTH, OUT_HEIGHT, OUT_WIDTH, I>
where
    I: Iterator<Item = T>,
    T: Default + Copy,
{
    pub fn new(iterator: I, width_ceil_calcs: &'a [u16], height_ceil_calcs: &'a [u16]) -> Self {
        Self {
            iterator,
            input_current_scan_line: 0,
            output_current_scan_line: 0,
            scaled_scan_line_buffer: [T::default(); OUT_WIDTH],
            scaled_line_buffer_repeat: 0,
            current_scaled_line_index: 0,
            width_ceil_calcs,
            height_ceil_calcs,
        }
    }
}

impl<
        'a,
        T,
        I,
        const IN_HEIGHT: usize,
        const IN_WIDTH: usize,
        const OUT_HEIGHT: usize,
        const OUT_WIDTH: usize,
    > Iterator for ScalerIterator<'a, T, IN_HEIGHT, IN_WIDTH, OUT_HEIGHT, OUT_WIDTH, I>
where
    I: Iterator<Item = T>,
    T: Copy,
{
    type Item = T;

    fn next(&mut self) -> Option<Self::Item> {
        loop {
            if self.scaled_line_buffer_repeat > 0 {
                let pixel = self.scaled_scan_line_buffer[self.current_scaled_line_index as usize];
                let next_current_scaled_line_index = self.current_scaled_line_index + 1;
                if next_current_scaled_line_index < OUT_WIDTH as u16 {
                    self.current_scaled_line_index = next_current_scaled_line_index;
                } else {
                    self.scaled_line_buffer_repeat -= 1;
                    self.current_scaled_line_index = 0;
                }
                return Some(pixel);
            }

            let mut next_x_position = 0;
            for count in 0..IN_WIDTH {
                match self.iterator.next() {
                    Some(pixel) => {
                        let last_pixel = self.width_ceil_calcs[count] as u16;
                        self.scaled_scan_line_buffer
                            [next_x_position as usize..last_pixel as usize]
                            .fill(pixel);
                        next_x_position = last_pixel;
                    }
                    None => return None,
                }
            }

            let next_scan_line_start =
                self.height_ceil_calcs[self.input_current_scan_line as usize] as u16;
            self.scaled_line_buffer_repeat = next_scan_line_start - self.output_current_scan_line;
            self.output_current_scan_line += self.scaled_line_buffer_repeat;

            if self.input_current_scan_line >= IN_HEIGHT as u16 - 1 {
                self.output_current_scan_line = 0;
                self.input_current_scan_line = 0;
            } else {
                self.input_current_scan_line += 1;
            }
        }
    }
}

#[inline(always)]
fn generate_scaling_ratio<const SIZE: usize>(ratio: f32) -> [u16; SIZE] {
    let mut width_ceil_calcs: [u16; SIZE] = [0u16; SIZE];
    let mut i = 0;
    while i < SIZE {
        width_ceil_calcs[i] = num_traits::Float::ceil(ratio * (i + 1) as f32) as u16;
        i += 1;
    }
    width_ceil_calcs
}
