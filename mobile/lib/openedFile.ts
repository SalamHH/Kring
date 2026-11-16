/** The app's OpenedStore, in a JSON file in the app's document directory. */
import { File, Paths } from 'expo-file-system';

import { OpenedStore } from './opened';

const file = new File(Paths.document, 'opened-incidents.json');

export const openedStore = new OpenedStore({
  read: () => (file.exists ? file.textSync() : null),
  write: (text) => {
    // The write finishes after markOpened returns, so its errors are caught here: a failed save
    // only means the badge may come back after a restart.
    Promise.resolve()
      .then(() => {
        if (!file.exists) file.create();
        return file.write(text);
      })
      .catch((e) => console.warn('opened: could not save the list', e));
  },
});
